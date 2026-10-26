"""Opportunity scoring (0-100) with a transparent breakdown.

Every component reports its points, its maximum, and *why*. Components that use AI output say so.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from . import analysis, clock
from .models import BodycamStatus, YouTubeStatus

BOOST_TERMS = re.compile(
    r"\b(naked|nude|alligator|gator|wrong[- ]way|stole a|stolen (?:bus|tractor|police car|patrol car|ambulance|boat)|"
    r"lawn ?mower|golf cart|horse|helicopter|k-?9|pit maneuver|flipped|rolled over|crashed into|"
    r"into a (?:pond|lake|canal|river|house|store)|hid (?:in|under)|jumped|tased|spike strips?|"
    r"stop sticks|bizarre|claimed|clown|costume|drunk|drag(?:ged)? |motorcycle|dirt bike|atv|"
    r"walmart|mcdonald'?s|drive[- ]thru|mugshot|viral)\b", re.I)

YT_POINTS = {
    YouTubeStatus.FOOTAGE: (0, "Footage of this incident already appears on YouTube"),
    YouTubeStatus.NEWS: (10, "News coverage on YouTube, but no bodycam upload found in checked results"),
    YouTubeStatus.COMMENTARY: (7, "Commentary videos exist; no bodycam upload found in checked results"),
    YouTubeStatus.RELATED_OTHER: (13, "Only videos about other incidents were found"),
    YouTubeStatus.NONE_FOUND: (15, "No matching videos in checked results (not proof it was never uploaded)"),
    YouTubeStatus.NOT_CHECKED: (8, "YouTube not checked yet (neutral)"),
}
FOOTAGE_POINTS = {
    BodycamStatus.RELEASED: (15, "Source reports footage was released"),
    BodycamStatus.YOUTUBE_FOUND: (15, "Footage found on YouTube"),
    BodycamStatus.MENTIONED: (12, "Source mentions body/dash camera"),
    BodycamStatus.LIKELY: (8, "Estimate: officer-contact incident at an agency likely using cameras"),
    BodycamStatus.UNKNOWN: (3, "No camera information"),
}
RISK_PENALTY = {"minor": 4, "victim": 3, "graphic": 3, "monetization": 2, "privacy": 1, "ongoing": 0}


def _component(points, maximum, why, basis="rule-based"):
    return {"points": round(points, 1), "max": maximum, "why": why, "basis": basis}


def score_case(*, headline: str, text: str, categories: list[str], outlets: int, has_official_source: bool,
               agency_basis: str | None, bodycam_status: str, youtube_status: str, matched_videos: list[dict],
               incident_date: date | None, first_published: datetime | None, state: str | None,
               risk: list[dict], trusted_portal: bool, records_page: bool, suspects: list[str],
               ai: dict | None = None, today: date | None = None) -> tuple[int, dict]:
    today = today or clock.today()
    bd: dict = {}

    # 1. Interest (25)
    base = max([analysis.CATEGORIES[c]["base_interest"] for c in categories if c in analysis.CATEGORIES] or [3])
    boosts = sorted({m.group(0).lower() for m in BOOST_TERMS.finditer(f"{headline} {text}")})
    rule_interest = min(10, base + min(3, len(boosts)) + (1 if len(set(categories) - {"arrest"}) >= 2 else 0))
    why = f"Category base {base}/10" + (f"; unusual elements: {', '.join(boosts[:4])}" if boosts else "")
    if ai and isinstance(ai.get("interest_score"), int):
        blended = (rule_interest + ai["interest_score"]) / 2
        bd["interest"] = _component(blended * 2.5, 25, f"{why}; AI: {ai.get('interest_reason', '')}",
                                    "rule + AI estimate")
    else:
        bd["interest"] = _component(rule_interest * 2.5, 25, why)

    # 2. Audience potential (10)
    pts = {0: 1, 1: 3, 2: 5, 3: 7, 4: 8}.get(outlets, 10)
    if boosts:
        pts = min(10, pts + 1)
    bd["audience"] = _component(pts, 10, f"Covered by {outlets} outlet(s)")

    # 3. Footage likelihood (15)
    fp, fwhy = FOOTAGE_POINTS.get(bodycam_status, (3, "No camera information"))
    if ai and isinstance(ai.get("footage_likelihood"), int) and bodycam_status in (BodycamStatus.LIKELY, BodycamStatus.UNKNOWN):
        fp = (fp + ai["footage_likelihood"] * 1.5) / 2
        bd["footage_likelihood"] = _component(fp, 15, f"{fwhy}; AI: {ai.get('footage_reason', '')}", "rule + AI estimate")
    else:
        bd["footage_likelihood"] = _component(fp, 15, fwhy)

    # 4. Not already published (15)
    yp, ywhy = YT_POINTS.get(youtube_status, (8, "Unknown"))
    if bodycam_status == BodycamStatus.RELEASED and youtube_status != YouTubeStatus.FOOTAGE:
        yp = min(yp, 6)
        ywhy += "; agency already released footage publicly, so others may upload soon"
    bd["unpublished"] = _component(yp, 15, ywhy)

    # 5. Competition (10)
    if youtube_status == YouTubeStatus.NOT_CHECKED:
        bd["competition"] = _component(5, 10, "YouTube not checked yet")
    else:
        n = len(matched_videos)
        views = sum(v.get("view_count") or 0 for v in matched_videos)
        cp = 10 if n == 0 else 7 if n == 1 else 4 if n <= 3 else 1
        if views > 500_000:
            cp = 0
        elif views > 100_000:
            cp = min(cp, 3)
        bd["competition"] = _component(cp, 10, f"{n} matching video(s), {views:,} total views")

    # 6. Recency (10)
    ref = incident_date or (first_published.date() if first_published else None)
    if ref:
        days = (today - ref).days
        rp = 10 if days <= 3 else 8 if days <= 7 else 6 if days <= 14 else 4 if days <= 30 else 2 if days <= 60 else 1
        bd["recency"] = _component(rp, 10, f"{days} day(s) since {'incident' if incident_date else 'first report'}")
    else:
        days = None
        bd["recency"] = _component(3, 10, "Date unknown")

    # 7. Acquisition ease (10)
    ap, notes = 5.0, []
    if trusted_portal:
        ap += 3
        notes.append("verified request channel found")
    elif records_page:
        ap += 1
        notes.append("records page found (portal not verified)")
    else:
        notes.append("no verified request channel yet")
    if state == "Pennsylvania":
        if days is not None and days > 60:
            ap = 0
            notes.append("PA Act 22 60-day request window has likely passed")
        else:
            ap -= 1
            notes.append("PA Act 22: strict 60-day window and certified-mail delivery")
    if state == "Texas" and not suspects:
        ap -= 1
        notes.append("TX requires the name of a person recorded (none found yet)")
    if state == "Wisconsin" and days is not None and days > 100:
        ap -= 3
        notes.append("WI minimum retention is 120 days; footage may be purged soon")
    if state == "California":
        ap -= 1
        notes.append("CA agencies may withhold non-critical footage as investigative records")
    if state == "Ohio":
        notes.append("OH agencies may charge up to $75/hr ($750 cap) for bodycam production")
    if any(f["flag"] == "ongoing" for f in risk):
        ap -= 2
        notes.append("ongoing investigation may delay release")
    bd["acquisition"] = _component(max(0, min(10, ap)), 10, "; ".join(notes))

    # 8. Source reliability (5)
    sp = 5 if has_official_source else 4 if outlets >= 2 else 3 if outlets == 1 else 1
    if agency_basis == "named in source":
        sp = min(5, sp + 1)
    bd["reliability"] = _component(sp, 5, ("Official agency source" if has_official_source else f"{outlets} news outlet(s)")
                                   + ("; agency named in source" if agency_basis == "named in source" else ""))

    penalties = []
    for f in risk:
        p = RISK_PENALTY.get(f["flag"], 0)
        if p:
            penalties.append({"flag": f["flag"], "label": f["label"], "points": -p})
    total = sum(c["points"] for c in bd.values()) + sum(p["points"] for p in penalties)
    total = int(round(max(0, min(100, total))))
    return total, {"components": bd, "penalties": penalties, "total": total}


def estimate_cost(state: str | None, agency_fee_text: str | None) -> tuple[float | None, str | None]:
    """Return (estimated USD, basis). None when nothing published supports an estimate."""
    if agency_fee_text:
        m = re.search(r"\$\s?(\d[\d,]*(?:\.\d{2})?)[^|]{0,80}?(?:video|recording|body|camera|footage|dvd|disc|hour)",
                      agency_fee_text, re.I) or re.search(r"\$\s?(\d[\d,]*(?:\.\d{2})?)", agency_fee_text)
        if m:
            return float(m.group(1).replace(",", "")), "first dollar amount in agency's published fee text (check details)"
    if state == "Ohio":
        return 75.0, "estimate: one hour of video at Ohio HB 315 maximum ($75/hr, $750 cap)"
    return None, None
