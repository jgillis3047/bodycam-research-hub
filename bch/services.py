"""Read/write helpers used by the Streamlit pages (keeps SQL out of the UI)."""
from __future__ import annotations

from . import clock
import subprocess
import sys
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from . import config, records
from .analysis import CATEGORY_LABELS
from .db import session_scope
from .models import (
    PENDING_REQUEST_STATUSES, Agency, BodycamStatus, Case, RecordsRequest, ResearchRun, YouTubeStatus,
)

CONFIRMED_FOOTAGE = {BodycamStatus.RELEASED, BodycamStatus.MENTIONED, BodycamStatus.YOUTUBE_FOUND}
NO_COVERAGE = {YouTubeStatus.NONE_FOUND, YouTubeStatus.RELATED_OTHER}


def metrics() -> dict:
    week = clock.utcnow() - timedelta(days=7)
    with session_scope() as s:
        visible = Case.hidden.is_(False)
        q = lambda *w: s.scalar(select(func.count(Case.id)).where(visible, *w)) or 0  # noqa: E731
        return {
            "total": q(),
            "new_week": q(Case.created_at >= week),
            "high_priority": q(Case.score >= 70),
            "confirmed_footage": q(Case.bodycam_status.in_(CONFIRMED_FOOTAGE)),
            "no_coverage": q(Case.youtube_status.in_(NO_COVERAGE)),
            "pending_requests": s.scalar(select(func.count(RecordsRequest.id)).where(
                RecordsRequest.status.in_(PENDING_REQUEST_STATUSES))) or 0,
        }


def latest_request_status(case: Case) -> str:
    if not case.requests:
        return "Not started"
    return sorted(case.requests, key=lambda r: r.updated_at or r.created_at)[-1].status


def cases_frame(include_hidden: bool = False) -> pd.DataFrame:
    with session_scope() as s:
        stmt = select(Case).options(selectinload(Case.agency), selectinload(Case.requests),
                                    selectinload(Case.articles))
        if not include_hidden:
            stmt = stmt.where(Case.hidden.is_(False))
        rows = []
        for c in s.scalars(stmt).all():
            portal = records.trusted_portal(c.agency)
            rows.append({
                "id": c.id,
                "Score": c.score,
                "Incident": c.headline,
                "State": c.state or "",
                "City": c.city or "",
                "County": c.county or "",
                "Incident Date": c.incident_date,
                "Date basis": c.incident_date_basis or "",
                "First Reported": c.first_published.date() if c.first_published else None,
                "Police Agency": c.agency_name or "Unknown",
                "Type": CATEGORY_LABELS.get(c.category or "", c.category or ""),
                "category": c.category or "",
                "Bodycam Status": c.bodycam_status,
                "YouTube Coverage": c.youtube_status,
                "Records Request Link": portal,
                "Portal": "Verified" if portal else ("Unverified" if c.agency and c.agency.portal_url else "Not found"),
                "Request Status": latest_request_status(c),
                "Est. Cost": c.est_cost,
                "Sources": len(c.articles),
                "Saved": c.saved,
                "Hidden": c.hidden,
                "Risks": ", ".join(f["flag"] for f in (c.risk_flags or [])),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["id", "Score", "Incident", "State", "City", "County", "Incident Date",
                                   "Date basis", "First Reported", "Police Agency", "Type", "category",
                                   "Bodycam Status", "YouTube Coverage", "Records Request Link", "Portal",
                                   "Request Status", "Est. Cost", "Sources", "Saved", "Hidden", "Risks"])
    return df.sort_values("Score", ascending=False, kind="stable") if not df.empty else df


def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if f.get("days"):
        limit = clock.today() - timedelta(days=int(f["days"]))
        ref = out["Incident Date"].where(out["Incident Date"].notna(), out["First Reported"])
        out = out[ref.apply(lambda d: d is not None and not pd.isna(d) and d >= limit)]
    if f.get("states"):
        out = out[out["State"].isin(f["states"])]
    if f.get("place"):
        p = f["place"].lower()
        out = out[out["City"].str.lower().str.contains(p, na=False) | out["County"].str.lower().str.contains(p, na=False)]
    if f.get("types"):
        out = out[out["category"].isin(f["types"])]
    if f.get("min_score"):
        out = out[out["Score"] >= f["min_score"]]
    if f.get("bodycam"):
        out = out[out["Bodycam Status"].isin(f["bodycam"])]
    if f.get("youtube"):
        out = out[out["YouTube Coverage"].isin(f["youtube"])]
    if f.get("request"):
        out = out[out["Request Status"].isin(f["request"])]
    if f.get("max_cost") is not None:
        known = out["Est. Cost"].notna()
        keep = (~known & f.get("include_unknown_cost", True)) | (known & (out["Est. Cost"] <= f["max_cost"]))
        out = out[keep]
    if f.get("saved_only"):
        out = out[out["Saved"]]
    if f.get("search"):
        q = f["search"].lower()
        out = out[out["Incident"].str.lower().str.contains(q, na=False, regex=False)
                  | out["Police Agency"].str.lower().str.contains(q, na=False, regex=False)]
    return out


def set_case_flag(case_id: int, *, saved: bool | None = None, hidden: bool | None = None, notes: str | None = None):
    with session_scope() as s:
        c = s.get(Case, case_id)
        if c is None:
            return
        if saved is not None:
            c.saved = saved
        if hidden is not None:
            c.hidden = hidden
        if notes is not None:
            c.user_notes = notes


def case_options(include_hidden: bool = False) -> list[tuple[int, str]]:
    with session_scope() as s:
        stmt = select(Case.id, Case.score, Case.headline, Case.state).order_by(Case.score.desc())
        if not include_hidden:
            stmt = stmt.where(Case.hidden.is_(False))
        return [(r.id, f"[{r.score}] {r.headline[:90]} ({r.state or '?'})") for r in s.execute(stmt).all()]


def load_case(case_id: int) -> Case | None:
    with session_scope() as s:
        return s.scalars(select(Case).options(
            selectinload(Case.articles), selectinload(Case.videos), selectinload(Case.requests),
            selectinload(Case.agency)).where(Case.id == case_id)).first()


def agencies_frame() -> pd.DataFrame:
    with session_scope() as s:
        rows = [{
            "id": a.id, "Agency": a.name, "State": a.state or "", "Type": a.agency_type or "",
            "Website": a.website, "Website status": a.website_status,
            "Portal": a.portal_url, "Portal status": a.portal_status,
            "Records e-mail": a.records_email or "", "E-mail status": a.email_status,
            "Cases": len(a.cases),
            "Last researched": a.last_researched_at.strftime("%Y-%m-%d") if a.last_researched_at else "",
        } for a in s.scalars(select(Agency).options(selectinload(Agency.cases)).order_by(Agency.name)).all()]
    return pd.DataFrame(rows)


def requests_frame() -> pd.DataFrame:
    with session_scope() as s:
        rows = [{
            "id": r.id, "Status": r.status, "Agency": r.agency_name or "", "Incident": r.incident or "",
            "Submitted": r.submitted_date, "Tracking #": r.tracking_number or "",
            "Quoted Fee": r.quoted_fee, "Paid": r.amount_paid, "Follow-up": r.follow_up_date,
            "Method": r.submission_method or "", "Response": r.response_info or "", "Notes": r.notes or "",
            "case_id": r.case_id,
        } for r in s.scalars(select(RecordsRequest).order_by(RecordsRequest.updated_at.desc())).all()]
    cols = ["id", "Status", "Agency", "Incident", "Submitted", "Tracking #", "Quoted Fee", "Paid",
            "Follow-up", "Method", "Response", "Notes", "case_id"]
    df = pd.DataFrame(rows, columns=cols)
    for c in ("Quoted Fee", "Paid"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    return df


def latest_runs(n: int = 10) -> list[ResearchRun]:
    with session_scope() as s:
        return s.scalars(select(ResearchRun).order_by(ResearchRun.started_at.desc()).limit(n)).all()


def launch_background_research() -> None:
    """Start run_research.py as a separate process so it survives page reloads."""
    script = config.PROJECT_ROOT / "run_research.py"
    kwargs: dict = {"cwd": str(config.PROJECT_ROOT)}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    log_path = config.DATA_DIR / "last_run_output.log"
    with open(log_path, "w", encoding="utf-8") as fh:
        subprocess.Popen([sys.executable, str(script), "--trigger", "dashboard"], stdout=fh, stderr=subprocess.STDOUT,
                         **kwargs)
