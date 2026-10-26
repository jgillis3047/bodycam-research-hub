"""YouTube Data API v3 integration: coverage detection for cases + competitor channel tracking.

Quota notes (default 10,000 units/day per Google Cloud project):
  search.list = 100 units, videos.list / channels.list / playlistItems.list = 1 unit.
Every call is cached and recorded against a local daily budget (setting youtube_daily_quota_budget).
"""
from __future__ import annotations

from . import clock
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import analysis, config, net
from .feeds import strip_html
from .models import YouTubeStatus

API = "https://www.googleapis.com/youtube/v3"
COSTS = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1}


class YouTubeError(Exception):
    pass


class QuotaExceeded(YouTubeError):
    pass


def api_key() -> str:
    return config.get_env("YOUTUBE_API_KEY")


def is_configured() -> bool:
    return bool(api_key())


# ---------------------------------------------------------------------------
# Quota bookkeeping
# ---------------------------------------------------------------------------
def _quota_state() -> dict:
    from .db import get_setting
    st = get_setting("youtube_quota_used") or {}
    today = clock.utcnow().strftime("%Y-%m-%d")  # Google resets at midnight Pacific; close enough
    if st.get("day") != today:
        st = {"day": today, "units": 0}
    return st


def quota_used_today() -> int:
    return int(_quota_state().get("units", 0))


def _charge(endpoint: str) -> None:
    from .db import get_setting, set_setting
    st = _quota_state()
    budget = int(get_setting("youtube_daily_quota_budget") or 8000)
    cost = COSTS.get(endpoint, 1)
    if st["units"] + cost > budget:
        raise QuotaExceeded(f"Local YouTube quota budget reached ({st['units']}/{budget} units today)")
    st["units"] += cost
    set_setting("youtube_quota_used", st)


def _call(endpoint: str, params: dict, ttl: timedelta = timedelta(hours=12)) -> dict:
    key = api_key()
    if not key:
        raise YouTubeError("YOUTUBE_API_KEY is not configured")
    full = dict(params)
    full["key"] = key
    # Cache check first so cached calls do not consume quota
    cache_key = net._cache_key(f"{API}/{endpoint}", full)
    cached = net._cache_get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached.text)
    _charge(endpoint)
    try:
        return net.get_json(f"{API}/{endpoint}", params=full, ttl=ttl)
    except net.AccessRestricted as exc:
        msg = str(exc)
        if "quota" in msg.lower():
            raise QuotaExceeded(msg) from exc
        raise YouTubeError(msg) from exc
    except Exception as exc:  # noqa: BLE001 - network/HTTP errors become YouTubeError
        raise YouTubeError(f"YouTube request failed: {exc}") from exc


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def test_key() -> str:
    """Cheap (1 unit) uncached call to validate the configured key."""
    if not api_key():
        raise YouTubeError("YOUTUBE_API_KEY is not configured")
    _charge("videos")
    try:
        data = net.get_json(f"{API}/videos", params={"part": "id", "chart": "mostPopular", "maxResults": 1,
                                                       "regionCode": "US", "key": api_key()}, use_cache=False)
    except net.AccessRestricted as exc:
        raise YouTubeError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise YouTubeError(f"Request failed: {exc}") from exc
    return f"OK ({len(data.get('items', []))} item returned)"


def search_videos(query: str, published_after: datetime | None = None, max_results: int = 15) -> list[dict]:
    params = {"part": "snippet", "q": query, "type": "video", "maxResults": min(50, max_results),
              "order": "relevance", "regionCode": "US", "relevanceLanguage": "en", "safeSearch": "none"}
    if published_after:
        params["publishedAfter"] = published_after.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = _call("search", params)
    ids = [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]
    return video_details(ids)


def video_details(ids: list[str]) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        if not chunk:
            continue
        data = _call("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(chunk)})
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            stats = it.get("statistics", {})
            thumbs = sn.get("thumbnails", {})
            thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
            out.append({
                "video_id": it["id"],
                "title": strip_html(sn.get("title", "")),
                "description": sn.get("description", "")[:2000],
                "channel_title": sn.get("channelTitle", ""),
                "channel_id": sn.get("channelId", ""),
                "published_at": _parse_dt(sn.get("publishedAt")),
                "view_count": int(stats["viewCount"]) if stats.get("viewCount") else None,
                "thumbnail_url": thumb,
                "duration": it.get("contentDetails", {}).get("duration"),
            })
    return out


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
FOOTAGE_RE = re.compile(
    r"\b(body[- ]?cam(?:era)?s?|bodycams?|body[- ]worn|bwc|dash[- ]?cam(?:era)?s?|dashboard camera|"
    r"cruiser cam|helicopter (?:video|footage)|(?:police|deputy|trooper|officer)[- ]?cam|"
    r"(?:police|sheriff'?s?) (?:release|releases|released) (?:video|footage)|911 (?:call|audio))\b", re.I)
NEGATED_FOOTAGE_RE = re.compile(
    r"\b(no (?:body ?cam|bodycam|body camera)|(?:has|have) not (?:been )?released|(?:won't|will not|refuse[sd]? to) release|"
    r"(?:calls?|push(?:es)?|demands?) (?:for|to) release)\b", re.I)
NEWS_CHANNEL_RE = re.compile(
    r"(\bnews\b|\b[KW][A-Z]{2,3}(?:-?TV)?\b|\b(?:fox|nbc|abc|cbs|cw)\s?\d+|\b\d+\s?(?:news|abc|nbc|cbs|fox)\b|"
    r"spectrum|nexstar|tegna|scripps|sinclair|gray tv|\bwptv\b|\bwfla\b|local 10|action news|eyewitness|"
    r"associated press|reuters|inside edition|\bcourt tv\b|law&crime|law & crime|\b(?:nbc|cbs|abc|fox)\b)", re.I)
AGENCY_CHANNEL_RE = re.compile(r"(police|sheriff|highway patrol|state patrol|state police|\bpd\b|"
                               r"department of public safety|county so\b)", re.I)


def channel_kind(channel_title: str) -> str:
    if AGENCY_CHANNEL_RE.search(channel_title or ""):
        return "agency"
    if NEWS_CHANNEL_RE.search(channel_title or ""):
        return "news"
    return "commentary"


def footage_signal(title: str, description: str) -> tuple[bool, str]:
    text = f"{title} {description[:600]}"
    if NEGATED_FOOTAGE_RE.search(text) and not FOOTAGE_RE.search(title):
        return False, ""
    m = FOOTAGE_RE.search(title) or FOOTAGE_RE.search(description[:600])
    if m:
        return True, m.group(0)
    return False, ""


@dataclass
class CaseContext:
    headline: str
    state: str | None
    city: str | None
    county: str | None
    agency: str | None
    incident_date: date | None
    published: datetime | None
    categories: list[str] = field(default_factory=list)
    suspects: list[str] = field(default_factory=list)


def _distinctive_terms(ctx: CaseContext) -> set[str]:
    toks = analysis.tokens(ctx.headline)
    generic = {"chase", "pursuit", "crash", "crashes", "driver", "stolen", "car", "vehicle", "dui",
               "robbery", "standoff", "home", "found", "charged", "faces", "charges", "jail",
               "deputies", "troopers", "bodycam", "footage", "camera", "body", "shows", "released"}
    return {t for t in toks if t not in generic}


def match_confidence(video: dict, ctx: CaseContext) -> tuple[int, list[str]]:
    """0-100 heuristic: does this video concern THIS incident?"""
    text = f"{video.get('title', '')} {video.get('description', '')[:800]}"
    low = text.lower()
    score = 0
    reasons: list[str] = []

    for name in ctx.suspects:
        last = name.split()[-1].lower()
        if name.lower() in low:
            score += 35
            reasons.append(f"suspect name '{name}'")
            break
        if len(last) > 3 and re.search(rf"\b{re.escape(last)}\b", low):
            score += 15
            reasons.append(f"suspect surname '{last}'")
            break
    if ctx.city and ctx.city.lower() in low:
        score += 20
        reasons.append(f"city '{ctx.city}'")
    if ctx.county and ctx.county.lower().replace(" county", "") in low:
        score += 12
        reasons.append(f"county '{ctx.county}'")
    if ctx.agency:
        core = re.sub(r"(police department|sheriff's office|sheriff's department|department|office)$", "",
                      ctx.agency.lower()).strip()
        if core and core in low.replace("’", "'"):
            score += 15
            reasons.append(f"agency '{ctx.agency}'")
    if ctx.state:
        if ctx.state.lower() in low or (analysis.US_STATES.get(ctx.state, "") and
                                        re.search(rf"\b{analysis.US_STATES[ctx.state]}\b", text)):
            score += 5
            reasons.append("same state")
        else:
            other = [s for s in analysis.detect_states(text) if s != ctx.state]
            if other:
                score -= 25
                reasons.append(f"mentions different state ({other[0]})")

    distinct = _distinctive_terms(ctx)
    overlap = distinct & analysis.tokens(text)
    if overlap:
        pts = min(25, 6 * len(overlap))
        score += pts
        reasons.append("shared terms: " + ", ".join(sorted(overlap)[:6]))
    cat_hits = [c for c in ctx.categories if c != "arrest" and analysis._CAT_RE[c].search(text)]
    if cat_hits:
        score += 8
        reasons.append(f"same incident type ({analysis.CATEGORY_LABELS[cat_hits[0]]})")

    ref = ctx.incident_date or (ctx.published.date() if ctx.published else None)
    pub = video.get("published_at")
    if ref and pub:
        delta = (pub.date() - ref).days
        if delta < -1:
            score -= 30
            reasons.append("uploaded before the incident")
        elif delta <= 21:
            score += 10
            reasons.append(f"uploaded {delta} day(s) after incident")
        elif delta > 365:
            score -= 10
            reasons.append("uploaded long after incident")
    return max(0, min(100, score)), reasons


MATCH_THRESHOLD = 55


def build_queries(ctx: CaseContext, n: int = 1) -> list[str]:
    place = ctx.city or (ctx.county or "")
    agency_short = ""
    if ctx.agency:
        agency_short = re.sub(r"(Police Department|Sheriff's Office|Sheriff's Department)$", "",
                              ctx.agency).strip()
        if "sheriff" in ctx.agency.lower():
            agency_short += " deputies"
        elif "police" in ctx.agency.lower():
            agency_short += " police"
    cat = next((c for c in ctx.categories if c != "arrest"), None)
    cat_word = {"pursuit": "chase", "dui": "DUI", "standoff": "standoff", "robbery": "robbery",
                "fleeing": "fled", "disorderly": "arrest", "traffic_stop": "traffic stop",
                "rescue": "rescue", "bizarre": "arrest", "confrontation": "arrest",
                "call_911": "911 call"}.get(cat or "", "arrest")
    queries = []
    if ctx.suspects:
        queries.append(f'"{ctx.suspects[0]}" {place}'.strip())
    base = " ".join(x for x in [place if place not in agency_short else "", agency_short, cat_word] if x)
    queries.append((base or ctx.headline[:80]).strip())
    hl = " ".join(list(_distinctive_terms(ctx))[:6])
    queries.append(f"{hl} {cat_word}".strip())
    seen, out = set(), []
    for q in queries:
        q = re.sub(r"\s+", " ", q)
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:max(1, n)]


def assess_videos(videos: list[dict], ctx: CaseContext) -> list[dict]:
    out = []
    for v in videos:
        conf, reasons = match_confidence(v, ctx)
        has, ev = footage_signal(v.get("title", ""), v.get("description", ""))
        v = dict(v)
        v.update(match_confidence=conf, match_reasons=reasons, has_footage=has,
                 footage_evidence=ev, channel_kind=channel_kind(v.get("channel_title", "")))
        out.append(v)
    out.sort(key=lambda v: -v["match_confidence"])
    return out


def coverage_status(assessed: list[dict]) -> str:
    matches = [v for v in assessed if v["match_confidence"] >= MATCH_THRESHOLD]
    if not assessed:
        return YouTubeStatus.NONE_FOUND
    if not matches:
        return YouTubeStatus.RELATED_OTHER
    if any(v["has_footage"] for v in matches):
        return YouTubeStatus.FOOTAGE
    if any(v["channel_kind"] in ("news", "agency") for v in matches):
        return YouTubeStatus.NEWS
    return YouTubeStatus.COMMENTARY


def research_case(ctx: CaseContext, n_queries: int = 1, per_query: int = 15) -> tuple[str, list[dict], list[str]]:
    ref = ctx.incident_date or (ctx.published.date() if ctx.published else None)
    after = datetime.combine(ref - timedelta(days=2), datetime.min.time()) if ref else None
    queries = build_queries(ctx, n_queries)
    seen: dict[str, dict] = {}
    for q in queries:
        for v in search_videos(q, after, per_query):
            v["query"] = q
            seen.setdefault(v["video_id"], v)
    assessed = assess_videos(list(seen.values()), ctx)
    return coverage_status(assessed), assessed, queries


# ---------------------------------------------------------------------------
# Competitor channels
# ---------------------------------------------------------------------------
def resolve_channel(handle_or_id: str) -> dict:
    h = handle_or_id.strip()
    m = re.search(r"youtube\.com/(?:channel/(UC[\w-]{20,})|(@[\w.\-]+))", h)
    if m:
        h = m.group(1) or m.group(2)
    params = {"part": "snippet,contentDetails,statistics"}
    if h.startswith("UC") and len(h) >= 22:
        params["id"] = h
    else:
        params["forHandle"] = h if h.startswith("@") else "@" + h
    data = _call("channels", params, ttl=timedelta(days=7))
    items = data.get("items") or []
    if not items:
        raise YouTubeError(f"No channel found for '{handle_or_id}'")
    it = items[0]
    sn, stats = it.get("snippet", {}), it.get("statistics", {})
    return {
        "channel_id": it["id"],
        "title": sn.get("title"),
        "uploads_playlist": it.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        "subscriber_count": int(stats["subscriberCount"]) if stats.get("subscriberCount") else None,
        "video_count": int(stats["videoCount"]) if stats.get("videoCount") else None,
        "thumbnail_url": (sn.get("thumbnails", {}).get("default") or {}).get("url"),
    }


def recent_uploads(uploads_playlist: str, max_items: int = 50) -> list[dict]:
    data = _call("playlistItems", {"part": "contentDetails", "playlistId": uploads_playlist,
                                   "maxResults": min(50, max_items)}, ttl=timedelta(hours=6))
    ids = [it["contentDetails"]["videoId"] for it in data.get("items", [])
           if it.get("contentDetails", {}).get("videoId")]
    return video_details(ids)


def iso_duration_to_text(value: str | None) -> str:
    if not value:
        return ""
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not m:
        return value
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    h += d * 24
    return f"{h}:{mi:02d}:{s:02d}" if h else f"{mi}:{s:02d}"
