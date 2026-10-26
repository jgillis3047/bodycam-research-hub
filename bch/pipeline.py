"""The research pipeline: discover -> extract -> dedupe -> evaluate -> YouTube -> records -> score -> save."""
from __future__ import annotations

from . import clock
import logging
import os
import re
import time
import traceback
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import ai, analysis, config, discovery, net, records, scoring, youtube
from .db import get_setting, init_db, session_scope, set_setting
from .models import (
    Agency, Article, BodycamStatus, Case, ChannelVideo, ResearchRun, Source, TrackedChannel,
    Verification, YouTubeStatus, YouTubeVideo,
)

log = logging.getLogger(__name__)
LOCK_PATH = config.DATA_DIR / "research.lock"
PROGRESS_PATH = config.DATA_DIR / "research_progress.json"
Progress = Callable[[float, str], None]


class RunLog:
    def __init__(self, progress: Progress | None):
        self.lines: list[str] = []
        self.progress = progress

    def __call__(self, msg: str, frac: float | None = None):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.lines.append(f"[{stamp}] {msg}")
        log.info(msg)
        if frac is not None:
            self.frac = frac
        try:
            import json as _json
            PROGRESS_PATH.write_text(_json.dumps({"frac": getattr(self, "frac", 0.0), "message": msg,
                                                  "lines": self.lines[-40:],
                                                  "updated": datetime.now().isoformat()}), encoding="utf-8")
        except OSError:
            pass
        if self.progress and frac is not None:
            try:
                self.progress(min(1.0, max(0.0, frac)), msg)
            except Exception:  # noqa: BLE001 - UI callback must never break the run
                pass


# ---------------------------------------------------------------------------
# Locking (UI button + scheduled task may overlap)
# ---------------------------------------------------------------------------
def _acquire_lock() -> bool:
    if LOCK_PATH.exists():
        age = time.time() - LOCK_PATH.stat().st_mtime
        if age < 3 * 3600:
            return False
        LOCK_PATH.unlink(missing_ok=True)
    LOCK_PATH.write_text(f"{os.getpid()} {datetime.now().isoformat()}", encoding="utf-8")
    return True


def _release_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)


def read_progress() -> dict | None:
    import json as _json
    try:
        return _json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_running() -> bool:
    return LOCK_PATH.exists() and time.time() - LOCK_PATH.stat().st_mtime < 3 * 3600


# ---------------------------------------------------------------------------
# Case building
# ---------------------------------------------------------------------------
def _article_text(a: Article) -> str:
    return " ".join(x for x in (a.title, a.summary, a.text_excerpt) if x)


def recompute_case(case: Case) -> None:
    """Re-derive every extracted field of a case from its articles."""
    arts = sorted(case.articles, key=lambda a: (not a.is_official, a.published_at or datetime.max))
    if not arts:
        return
    texts = [_article_text(a) for a in arts]
    combined = " \n ".join(texts)
    hints = Counter(a.state_hint for a in arts if a.state_hint)
    hint = hints.most_common(1)[0][0] if hints else None

    lead = arts[0]
    case.headline = lead.title[:500]
    best_summary = max(arts, key=lambda a: len(a.text_excerpt or a.summary or ""))
    summ = (best_summary.text_excerpt or best_summary.summary or "").strip()
    if summ:
        sentences = re.split(r"(?<=[.!?])\s+", summ)
        case.summary = " ".join(sentences[:3])[:700]
        case.summary_source_url = best_summary.url
    else:
        case.summary = None
        case.summary_source_url = lead.url

    case.state, case.state_basis = analysis.resolve_state(combined, hint)
    case.agency_name, case.agency_basis = analysis.pick_agency(texts, case.state)
    case.city, case.county, case.location_basis = analysis.extract_location(combined, case.state, case.agency_name)

    best = (None, "not stated in checked sources", "", -1)
    for a in sorted(arts, key=lambda a: a.published_at or datetime.max):
        d, basis, ev = analysis.extract_incident_date(_article_text(a), a.published_at, case.state)
        rank = analysis.DATE_BASIS_RANK.get(basis, 0) if d else -1
        if rank > best[3]:
            best = (d, basis, f'"{ev}" in {a.source_name or a.source_domain}' if ev else "", rank)
    case.incident_date, case.incident_date_basis, case.incident_date_evidence = best[0], best[1], best[2]

    pubs = [a.published_at for a in arts if a.published_at]
    case.first_published = min(pubs) if pubs else None
    case.last_published = max(pubs) if pubs else None

    cats = Counter()
    for t in texts:
        for i, c in enumerate(analysis.detect_categories(t)):
            cats[c] += 3 - min(i, 2)
    ranked = [c for c, _ in cats.most_common()]
    ranked.sort(key=lambda c: c == "arrest")
    case.categories = ranked
    case.category = ranked[0] if ranked else None

    yt_footage = case.bodycam_status == BodycamStatus.YOUTUBE_FOUND
    status, ev = analysis.detect_bodycam(combined, ranked, case.agency_name)
    if not (yt_footage and status in (BodycamStatus.LIKELY, BodycamStatus.UNKNOWN, BodycamStatus.MENTIONED)):
        case.bodycam_status, case.bodycam_evidence = status, ev
    case.suspect_names = analysis.extract_suspects(combined)
    case.risk_flags = analysis.risk_flags(combined)

    timeline = []
    if case.incident_date:
        timeline.append({"date": case.incident_date.isoformat(), "event": "Incident (per source)",
                         "detail": f"{case.incident_date_basis}: {case.incident_date_evidence}", "url": None})
    for a in sorted(arts, key=lambda a: a.published_at or datetime.max):
        timeline.append({"date": a.published_at.isoformat(sep=" ", timespec="minutes") if a.published_at else "",
                         "event": f"Reported by {a.source_name or a.source_domain}", "detail": a.title, "url": a.url})
    case.timeline = timeline


def case_candidate(case: Case) -> analysis.Candidate:
    text = " ".join(_article_text(a) for a in case.articles[:3])
    return analysis.Candidate(key=f"case:{case.id}", title=case.headline, text=text,
                              published=case.first_published, state=case.state, agency=case.agency_name,
                              city=case.city, categories=case.categories or [])


def item_candidate(i: int, item: discovery.RawItem) -> analysis.Candidate:
    text = item.text
    state, _ = analysis.resolve_state(text, item.state_hint)
    agency, _ = analysis.pick_agency([text], state)
    city, _, _ = analysis.extract_location(text, state, agency)
    return analysis.Candidate(key=str(i), title=item.title, text=" ".join([item.summary, item.text_excerpt]),
                              published=item.published, state=state, agency=agency, city=city,
                              categories=analysis.detect_categories(text))


def ensure_agency(s: Session, case: Case) -> Agency | None:
    if not case.agency_name:
        return None
    norm = analysis.normalize_agency(case.agency_name)
    ag = s.scalars(select(Agency).where(Agency.normalized_name == norm, Agency.state == case.state)).first()
    if ag is None:
        ag = Agency(name=case.agency_name, normalized_name=norm, state=case.state,
                    agency_type=analysis.classify_agency(case.agency_name),
                    county=case.county if "sheriff" in norm or "county" in norm else None,
                    city=case.city if analysis.classify_agency(case.agency_name) == "police" else None,
                    candidates=[], evidence=[])
        s.add(ag)
        s.flush()
    case.agency = ag
    return ag


def score(case: Case) -> None:
    matched = [{"view_count": v.view_count} for v in case.videos if v.match_confidence >= youtube.MATCH_THRESHOLD]
    outlets = len({(a.source_name or a.source_domain or "").lower() for a in case.articles})
    total, breakdown = scoring.score_case(
        headline=case.headline, text=" ".join(_article_text(a) for a in case.articles),
        categories=case.categories or [], outlets=outlets,
        has_official_source=any(a.is_official for a in case.articles),
        agency_basis=case.agency_basis, bodycam_status=case.bodycam_status,
        youtube_status=case.youtube_status, matched_videos=matched, incident_date=case.incident_date,
        first_published=case.first_published, state=case.state, risk=case.risk_flags or [],
        trusted_portal=bool(records.trusted_portal(case.agency) or records.trusted_email(case.agency)),
        records_page=bool(case.agency and case.agency.records_page_url),
        suspects=case.suspect_names or [], ai=case.ai_assessment)
    case.score, case.score_breakdown = total, breakdown
    case.est_cost, case.est_cost_basis = scoring.estimate_cost(case.state, case.agency.fee_info if case.agency else None)


def apply_youtube(s: Session, case: Case, status: str, assessed: list[dict], queries: list[str]) -> None:
    existing = {v.video_id: v for v in case.videos}
    for v in assessed[:25]:
        row = existing.get(v["video_id"])
        if row is None:
            row = YouTubeVideo(case_id=case.id, video_id=v["video_id"])
            s.add(row)
            case.videos.append(row)
        for k in ("title", "description", "channel_title", "channel_id", "published_at", "view_count",
                  "thumbnail_url", "match_confidence", "match_reasons", "channel_kind", "has_footage",
                  "footage_evidence", "query"):
            setattr(row, k, v.get(k))
    case.youtube_status = status
    case.youtube_checked_at = clock.utcnow()
    case.youtube_queries = queries
    if status == YouTubeStatus.FOOTAGE and case.bodycam_status != BodycamStatus.RELEASED:
        case.bodycam_status = BodycamStatus.YOUTUBE_FOUND
        top = next(v for v in assessed if v["has_footage"] and v["match_confidence"] >= youtube.MATCH_THRESHOLD)
        case.bodycam_evidence = f"YouTube: \"{top['title']}\" ({top['channel_title']})"


def youtube_context(case: Case) -> youtube.CaseContext:
    return youtube.CaseContext(headline=case.headline, state=case.state, city=case.city, county=case.county,
                               agency=case.agency_name, incident_date=case.incident_date,
                               published=case.first_published, categories=case.categories or [],
                               suspects=case.suspect_names or [])


def check_case_youtube(case_id: int) -> str:
    """Run YouTube coverage detection for a single case (used by the Case Research page)."""
    with session_scope() as s:
        case = s.get(Case, case_id)
        status, assessed, queries = youtube.research_case(
            youtube_context(case), int(get_setting("youtube_queries_per_case") or 1),
            int(get_setting("youtube_results_per_query") or 15))
        apply_youtube(s, case, status, assessed, queries)
        score(case)
        return status


def research_agency_by_id(agency_id: int) -> records.ResearchResult:
    with session_scope() as s:
        ag = s.get(Agency, agency_id)
        res = records.research_agency(ag)
        records.apply_result(ag, res)
        for c in ag.cases:
            score(c)
        return res


def refresh_competition(s: Session, rl: RunLog) -> int:
    n = 0
    for ch in s.scalars(select(TrackedChannel).where(TrackedChannel.enabled.is_(True))).all():
        try:
            if not ch.uploads_playlist:
                info = youtube.resolve_channel(ch.channel_id or ch.handle)
                for k, v in info.items():
                    setattr(ch, k, v)
            vids = youtube.recent_uploads(ch.uploads_playlist, 50)
        except youtube.YouTubeError as exc:
            ch.last_status = f"Error: {exc}"
            rl(f"Competition: {ch.handle}: {exc}")
            continue
        recent_cases = s.scalars(select(Case).where(Case.first_published >= clock.utcnow() - timedelta(days=120))).all()
        ctxs = [(c, youtube_context(c)) for c in recent_cases]
        for v in vids:
            row = s.scalars(select(ChannelVideo).where(ChannelVideo.video_id == v["video_id"])).first()
            if row is None:
                row = ChannelVideo(channel_pk=ch.id, video_id=v["video_id"], title=v["title"])
                s.add(row)
            row.title, row.description = v["title"], v.get("description")
            row.published_at, row.view_count = v.get("published_at"), v.get("view_count")
            row.thumbnail_url, row.duration = v.get("thumbnail_url"), v.get("duration")
            text = f"{v['title']} {v.get('description', '')[:500]}"
            states = analysis.detect_states(text)
            row.detected_state = states[0] if states else None
            cats = analysis.detect_categories(text)
            row.detected_category = cats[0] if cats else None
            best = max(((youtube.match_confidence(v, ctx)[0], c.id) for c, ctx in ctxs), default=(0, None))
            row.matched_case_id = best[1] if best[0] >= youtube.MATCH_THRESHOLD else None
            n += 1
        ch.last_checked = clock.utcnow()
        ch.last_status = f"OK - {len(vids)} recent uploads"
    return n


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_research(trigger: str = "manual", progress: Progress | None = None,
                 skip_youtube: bool = False, skip_records: bool = False) -> dict:
    init_db()
    rl = RunLog(progress)
    if not _acquire_lock():
        rl("Another research run is already in progress. Try again later.", 1.0)
        return {"status": "skipped", "reason": "already running"}

    stats: Counter = Counter()
    with session_scope() as s:
        run = ResearchRun(trigger=trigger, status="running")
        s.add(run)
        s.flush()
        run_id = run.id

    status = "completed"
    try:
        settings = {k: get_setting(k) for k in config.DEFAULT_SETTINGS}
        net.configure(settings["http_delay_seconds"], settings["contact_email_for_user_agent"]
                      or settings["request_contact"].get("email", ""))
        days = int(settings["lookback_days"])
        cutoff = clock.utcnow() - timedelta(days=days)

        # 1. Collect -----------------------------------------------------------
        plan = discovery.build_search_plan(settings["states"], settings["categories"], settings["extra_locations"])
        raw: list[discovery.RawItem] = []
        total_steps = len(plan) * (int(settings["enable_google_news"]) + int(settings["enable_bing_news"])) or 1
        step = 0
        consecutive_fail = Counter()
        for task in plan:
            for name, enabled, fn in (("Google News", settings["enable_google_news"], discovery.fetch_google_news),
                                      ("Bing News", settings["enable_bing_news"], discovery.fetch_bing_news)):
                if not enabled or consecutive_fail[name] >= 5:
                    continue
                step += 1
                try:
                    got = fn(task, days)
                    raw.extend(got)
                    stats[f"items_{name}"] += len(got)
                    consecutive_fail[name] = 0
                    rl(f"{name}: {len(got)} results for {task.state} / {task.category or task.location}",
                       0.30 * step / total_steps)
                except net.AccessRestricted as exc:
                    consecutive_fail[name] += 5  # stop using a source that blocks us
                    stats["source_errors"] += 1
                    rl(f"{name} blocked access ({exc}); skipping this source for the rest of the run")
                except Exception as exc:  # noqa: BLE001
                    consecutive_fail[name] += 1
                    stats["source_errors"] += 1
                    rl(f"{name} error for '{task.query}': {exc}")
                    if consecutive_fail[name] >= 5:
                        rl(f"{name} failed 5 times in a row - check your internet connection. Skipping it this run.")
        with session_scope() as s:
            sources = s.scalars(select(Source).where(Source.enabled.is_(True))).all()
            for src in sources:
                try:
                    got = discovery.fetch_configured_feed(src.url, src.name, src.state, src.is_official)
                    raw.extend(got)
                    src.last_status = f"OK - {len(got)} items"
                    stats["items_feeds"] += len(got)
                except Exception as exc:  # noqa: BLE001
                    src.last_status = f"Error: {exc}"[:300]
                    rl(f"Feed '{src.name}' failed: {exc}")
                src.last_fetched = clock.utcnow()
        stats["items_collected"] = len(raw)
        rl(f"Collected {len(raw)} items", 0.32)

        # 2. Filter -------------------------------------------------------------
        with session_scope() as s:
            known_urls = set(s.scalars(select(Article.url)).all())
        uniq: dict[str, discovery.RawItem] = {}
        for it in raw:
            if not it.url or it.url in known_urls or it.url in uniq:
                continue
            if it.published and it.published < cutoff:
                stats["skipped_old"] += 1
                continue
            ok, _why = analysis.is_relevant(it.text)
            if not ok:
                stats["skipped_irrelevant"] += 1
                continue
            uniq[it.url] = it
        items = list(uniq.values())
        rl(f"{len(items)} new relevant articles after filtering", 0.35)

        # 3. Enrich -------------------------------------------------------------
        if settings["fetch_article_pages"]:
            budget = int(settings["max_article_fetches_per_run"])
            for i, it in enumerate([x for x in items if discovery.can_enrich(x)][:budget]):
                discovery.enrich(it)
                if it.fetched_full_text:
                    stats["articles_enriched"] += 1
                if i % 5 == 0:
                    rl(f"Reading article pages ({i + 1})", 0.35 + 0.1 * i / max(1, budget))

        # 4. Dedupe + merge -----------------------------------------------------
        with session_scope() as s:
            recent = s.scalars(select(Case).options(selectinload(Case.articles))
                               .where(Case.first_published >= clock.utcnow() - timedelta(days=days + 10))).all()
            existing = [(c, case_candidate(c)) for c in recent]
            cands = [item_candidate(i, it) for i, it in enumerate(items)]
            groups = analysis.cluster(cands)
            touched: set[int] = set()
            for g in groups:
                target = None
                for c, cc in existing:
                    if any(analysis.same_incident(m, cc) for m in g):
                        target = c
                        break
                if target is None:
                    target = Case(headline=items[int(g[0].key)].title[:500], categories=[], risk_flags=[],
                                  suspect_names=[], timeline=[], youtube_queries=[], score_breakdown={})
                    s.add(target)
                    s.flush()
                    stats["cases_new"] += 1
                    existing.append((target, g[0]))
                else:
                    stats["cases_updated"] += 1
                for m in g:
                    it = items[int(m.key)]
                    s.add(Article(case_id=target.id, url=it.url[:1000], title=it.title[:500],
                                  source_name=it.source_name[:200] if it.source_name else None,
                                  source_domain=it.source_domain, published_at=it.published,
                                  summary=it.summary, text_excerpt=it.text_excerpt, collector=it.collector,
                                  query=it.query[:500], state_hint=it.state_hint, is_official=it.is_official,
                                  fetched_full_text=it.fetched_full_text))
                touched.add(target.id)
            s.flush()
            for cid in touched:
                c = s.get(Case, cid)
                s.refresh(c)
                recompute_case(c)
                ensure_agency(s, c)
                if c.state not in settings["states"] and c.state_basis == "named in source":
                    # Out-of-area story returned by a broad search: keep but hide by default
                    if not any(loc.get("state") == c.state for loc in settings["extra_locations"]):
                        c.hidden = True
                        stats["hidden_out_of_area"] += 1
                score(c)
        rl(f"Cases: {stats['cases_new']} new, {stats['cases_updated']} updated", 0.5)

        # 5. AI (optional) ------------------------------------------------------
        if ai.is_enabled():
            with session_scope() as s:
                todo = s.scalars(select(Case).where(Case.ai_assessment.is_(None), Case.hidden.is_(False))
                                 .order_by(Case.score.desc()).limit(int(settings["ai_max_cases_per_run"]))).all()
                for c in todo:
                    try:
                        c.ai_assessment = ai.assess_case("\n\n".join(
                            f"[{a.source_name}] {_article_text(a)}" for a in c.articles[:4]))
                        stats["ai_assessed"] += 1
                        score(c)
                    except Exception as exc:  # noqa: BLE001
                        rl(f"AI assessment failed for case {c.id}: {exc}")
                        break
            rl(f"AI assessed {stats['ai_assessed']} case(s)", 0.55)
        else:
            rl("AI not configured - using rule-based analysis only", 0.55)

        # 6. YouTube --------------------------------------------------------------
        if skip_youtube:
            pass
        elif not youtube.is_configured():
            rl("YouTube API key not set - coverage checks skipped (cases show 'Not checked')", 0.7)
        else:
            recheck = clock.utcnow() - timedelta(days=int(settings["youtube_recheck_days"]))
            with session_scope() as s:
                todo = s.scalars(select(Case).where(
                    Case.hidden.is_(False), Case.first_published >= cutoff - timedelta(days=7),
                    (Case.youtube_checked_at.is_(None)) | (Case.youtube_checked_at < recheck))
                    .order_by(Case.score.desc()).limit(int(settings["youtube_max_cases_per_run"]))).all()
                for i, c in enumerate(todo):
                    try:
                        st, assessed, queries = youtube.research_case(
                            youtube_context(c), int(settings["youtube_queries_per_case"]),
                            int(settings["youtube_results_per_query"]))
                        apply_youtube(s, c, st, assessed, queries)
                        score(c)
                        stats["youtube_checked"] += 1
                        s.commit()
                    except youtube.QuotaExceeded as exc:
                        rl(f"YouTube quota: {exc}. Remaining cases will be checked next run.")
                        break
                    except youtube.YouTubeError as exc:
                        rl(f"YouTube error: {exc}")
                        break
                    rl(f"YouTube checked {i + 1}/{len(todo)}", 0.55 + 0.2 * (i + 1) / max(1, len(todo)))
                try:
                    stats["competition_videos"] = refresh_competition(s, rl)
                except youtube.YouTubeError as exc:
                    rl(f"Competition refresh failed: {exc}")

        # 7. Records custodian research ----------------------------------------
        if not skip_records:
            stale = clock.utcnow() - timedelta(days=int(settings["records_recheck_days"]))
            with session_scope() as s:
                ags = s.scalars(select(Agency).join(Case, Case.agency_id == Agency.id).where(
                    Case.hidden.is_(False),
                    (Agency.last_researched_at.is_(None)) | (Agency.last_researched_at < stale))
                    .group_by(Agency.id).order_by(func.max(Case.score).desc())
                    .limit(int(settings["records_max_agencies_per_run"]))).all()
                for i, ag in enumerate(ags):
                    try:
                        res = records.research_agency(ag)
                        records.apply_result(ag, res)
                        stats["agencies_researched"] += 1
                        if ag.portal_status in Verification.TRUSTED:
                            stats["portals_found"] += 1
                    except Exception as exc:  # noqa: BLE001
                        rl(f"Records research failed for {ag.name}: {exc}")
                    s.commit()
                    rl(f"Records research {i + 1}/{len(ags)}: {ag.name}", 0.75 + 0.2 * (i + 1) / max(1, len(ags)))

        # 8. Final scoring ------------------------------------------------------
        with session_scope() as s:
            for c in s.scalars(select(Case).where(Case.first_published >= clock.utcnow() - timedelta(days=90))).all():
                score(c)
        net.purge_cache()
        if stats["source_errors"] and not stats["items_collected"]:
            status = "completed_with_errors"
            rl("No news sources could be reached - see the errors above.", 1.0)
        else:
            rl("Research complete", 1.0)
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        rl(f"Run failed: {exc}\n{traceback.format_exc()}", 1.0)
    finally:
        with session_scope() as s:
            run = s.get(ResearchRun, run_id)
            run.finished_at = clock.utcnow()
            run.status = status
            run.stats = dict(stats)
            run.log = "\n".join(rl.lines)[-60000:]
        set_setting("last_run", {"at": clock.utcnow().isoformat(), "status": status, "trigger": trigger})
        _release_lock()
    return {"status": status, "stats": dict(stats), "log": rl.lines}
