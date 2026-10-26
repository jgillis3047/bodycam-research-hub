"""Page 3 - Case Research: criminal case | YouTube | footage acquisition, side by side."""
from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from .. import pipeline, records, services, youtube
from ..analysis import CATEGORY_LABELS
from ..db import session_scope
from ..models import REQUEST_STATUSES, Case, RecordsRequest, Verification, YouTubeStatus
from ..state_laws import law_for
from . import common

COMPONENT_LABELS = {
    "interest": "Interest / unusualness", "audience": "Audience potential",
    "footage_likelihood": "Footage likely exists", "unpublished": "Not already on YouTube",
    "competition": "YouTube competition", "recency": "Recency", "acquisition": "Ease of acquisition",
    "reliability": "Source reliability",
}


def _left(case: Case) -> None:
    st.markdown("### Criminal case research")
    with st.container(border=True):
        if case.summary:
            st.markdown(case.summary)
            if case.summary_source_url:
                st.markdown(f"[Summary source]({case.summary_source_url})")
        else:
            st.caption("No article text available beyond the headline. Open the sources below.")
        st.markdown("**Date & location**")
        date_txt = case.incident_date.strftime("%a %b %d, %Y") if case.incident_date else "Unknown"
        common.show_badges((f"Incident: {date_txt}", common.basis_color(case.incident_date_basis)))
        st.caption(f"Date basis: {case.incident_date_basis or 'unknown'}"
                   + (f" - {case.incident_date_evidence}" if case.incident_date_evidence else ""))
        if case.first_published:
            st.caption(f"First reported: {case.first_published:%Y-%m-%d %H:%M} UTC (article publish date, not incident date)")
        loc = ", ".join(x for x in [case.city, case.county, case.state] if x) or "Unknown"
        common.show_badges((loc, common.basis_color(case.location_basis)))
        st.caption(f"Location basis: {case.location_basis or 'unknown'}; state basis: {case.state_basis or 'unknown'}")
        st.markdown("**Agency**")
        common.show_badges((case.agency_name or "Not identified", common.basis_color(case.agency_basis)))
        st.caption(f"Agency basis: {case.agency_basis or 'unknown'}")
        st.markdown("**Incident type**")
        common.show_badges(*[(CATEGORY_LABELS.get(c, c), "blue") for c in (case.categories or [])[:4]])
        if case.suspect_names:
            st.markdown("**Names in reporting:** " + ", ".join(case.suspect_names))

    st.markdown("**Source articles**")
    for a in sorted(case.articles, key=lambda a: a.published_at or datetime.min):
        when = a.published_at.strftime("%Y-%m-%d") if a.published_at else "date ?"
        tag = " (official)" if a.is_official else ""
        st.markdown(f"- [{a.title}]({a.url}) - *{a.source_name or a.source_domain}{tag}*, {when}")
    st.markdown("**Incident timeline**")
    if case.timeline:
        for t in case.timeline:
            link = f" [link]({t['url']})" if t.get("url") else ""
            st.markdown(f"- `{t['date'] or '?'}` {t['event']}{link}  \n  <span class='bch-muted'>{t.get('detail', '')}</span>",
                        unsafe_allow_html=True)
    for r in case.requests:
        st.markdown(f"- Records request: **{r.status}**" + (f" (submitted {r.submitted_date})" if r.submitted_date else ""))


def _video_card(v) -> None:
    c1, c2 = st.columns([1, 2])
    if v.thumbnail_url:
        c1.image(v.thumbnail_url, width="stretch")
    with c2:
        st.markdown(f"[{v.title}]({v.url})")
        st.caption(f"{v.channel_title} - {v.published_at:%Y-%m-%d} - {common.fmt_views(v.view_count)} views"
                   if v.published_at else f"{v.channel_title} - {common.fmt_views(v.view_count)} views")
        badges = [(f"Match {v.match_confidence}%", "green" if v.match_confidence >= 70 else "amber" if v.match_confidence >= youtube.MATCH_THRESHOLD else "grey"),
                  (v.channel_kind or "?", "blue")]
        if v.has_footage:
            badges.append((f"Footage: '{v.footage_evidence}'", "red"))
        common.show_badges(*badges)
        if v.match_reasons:
            st.caption("Why: " + "; ".join(v.match_reasons[:5]))


def _middle(case: Case) -> None:
    st.markdown("### YouTube research")
    with st.container(border=True):
        common.show_badges((case.youtube_status, common.youtube_color(case.youtube_status)))
        if case.youtube_checked_at:
            st.caption(f"Checked {case.youtube_checked_at:%Y-%m-%d %H:%M} UTC with: "
                       + " | ".join(f"`{q}`" for q in (case.youtube_queries or [])))
        if case.youtube_status == YouTubeStatus.NONE_FOUND:
            st.caption("No matching videos in the checked results. This does not prove it was never uploaded.")
        if youtube.is_configured():
            if st.button("Check YouTube now", key="yt_check", help="Uses ~100-300 API units"):
                with st.spinner("Searching YouTube..."):
                    try:
                        st.success(f"Result: {pipeline.check_case_youtube(case.id)}")
                    except youtube.YouTubeError as exc:
                        st.error(str(exc))
                st.rerun()
        else:
            st.warning("Add a YouTube API key in Settings to enable coverage checks.")
        st.markdown(f"**Bodycam release status:** {case.bodycam_status}")
        if case.bodycam_evidence:
            st.caption(case.bodycam_evidence)

    vids = sorted(case.videos, key=lambda v: -v.match_confidence)
    matches = [v for v in vids if v.match_confidence >= youtube.MATCH_THRESHOLD]
    others = [v for v in vids if v.match_confidence < youtube.MATCH_THRESHOLD]
    st.markdown(f"**Likely matches for this incident ({len(matches)})**")
    if not matches:
        st.caption("None in checked results.")
    for v in matches[:8]:
        with st.container(border=True):
            _video_card(v)
    if others:
        with st.expander(f"Other search results - probably different incidents ({len(others)})"):
            for v in others[:15]:
                _video_card(v)


def _right(case: Case) -> None:
    st.markdown("### Footage acquisition")
    ag = case.agency
    law = law_for(case.state)
    st.markdown('<div class="bch-acq">', unsafe_allow_html=True)
    st.markdown(f"**Responsible agency:** {ag.name if ag else (case.agency_name or 'Not identified')}")
    if case.agency_basis and case.agency_basis != "named in source":
        st.caption(f"Agency is {case.agency_basis} - confirm before requesting.")
    portal = records.trusted_portal(ag)
    if portal:
        st.link_button("Open Records Request Portal", portal, type="primary", width="stretch")
        common.show_badges((ag.portal_status, common.verification_color(ag.portal_status)),
                           (ag.portal_platform or "portal", "blue"))
    else:
        st.error("Official request portal not verified yet.")
        if ag and ag.portal_url:
            st.caption(f"Unverified candidate: {ag.portal_url} - confirm it on the Footage Request Research page.")
    email = records.trusted_email(ag)
    if email:
        st.markdown(f"**Records e-mail:** [{email}](mailto:{email})")
        common.show_badges((ag.email_status, common.verification_color(ag.email_status)))
    if ag and ag.website:
        st.markdown(f"**Agency website:** [{ag.website}]({ag.website})")
        common.show_badges((ag.website_status, common.verification_color(ag.website_status)))
    if ag and ag.records_page_url:
        st.markdown(f"**Records page:** [{ag.records_page_url}]({ag.records_page_url})")
    if ag and ag.records_phone:
        st.markdown(f"**Records phone (from site):** {ag.records_phone}")
    st.markdown("</div>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown(f"**{law['law_name']}**  \n<span class='bch-muted'>{law['citation']}</span>", unsafe_allow_html=True)
        if law.get("statute_url"):
            st.markdown(f"[Statute / official reference]({law['statute_url']})")
        st.markdown(f"**Response time:** {law['response_time']}")
        for req in law.get("special_requirements", []):
            st.markdown(f"- :orange[{req}]")
        st.markdown("**Potential fees**")
        if ag and ag.fee_info:
            st.markdown(f"Published by agency: {ag.fee_info[:400]}")
            if ag.fee_source_url:
                st.caption(f"[Fee source]({ag.fee_source_url})")
        else:
            st.caption("No agency fee schedule found. State rule: " + law["fees"])
        if case.est_cost is not None:
            common.show_badges((f"Estimate: ${case.est_cost:,.0f}", "purple"))
            st.caption(case.est_cost_basis or "")
        st.markdown("**Potential legal restrictions**")
        for r in law.get("bodycam_rules", [])[:3]:
            st.caption(f"- {r}")
        st.caption("Informational summary only, not legal advice. Verify current law.")
    if ag and ag.request_instructions:
        with st.expander("Request instructions", expanded=False):
            st.markdown(ag.request_instructions.replace("\n", "  \n"))

    c1, c2 = st.columns(2)
    if c1.button("Generate Records Request", type="primary", width="stretch"):
        st.session_state["case_id"] = case.id
        st.session_state["autogen"] = True
        st.switch_page(common.PAGES["footage"])
    if ag and c2.button("Research agency now", width="stretch", help="Looks for the official site, records page and portal"):
        with st.spinner("Researching agency website..."):
            res = pipeline.research_agency_by_id(ag.id)
        st.info("\n".join(res.log[-6:]) or "Done")
        st.rerun()

    st.markdown("**Request tracking**")
    current = services.latest_request_status(case)
    new = st.selectbox("Status", ["Not started"] + REQUEST_STATUSES,
                       index=(["Not started"] + REQUEST_STATUSES).index(current), key="case_req_status")
    if new != current and st.button("Update status"):
        with session_scope() as s:
            req = s.query(RecordsRequest).filter_by(case_id=case.id).order_by(RecordsRequest.updated_at.desc()).first()
            if req is None and new != "Not started":
                req = RecordsRequest(case_id=case.id, agency_id=ag.id if ag else None,
                                     agency_name=ag.name if ag else case.agency_name, incident=case.headline[:500])
                s.add(req)
            if req is not None:
                req.status = new if new != "Not started" else "Researching"
                if new == "Submitted" and not req.submitted_date:
                    req.submitted_date = date.today()
        st.rerun()


def _scoring(case: Case) -> None:
    bd = case.score_breakdown or {}
    comps = bd.get("components", {})
    with st.expander("Score breakdown", expanded=True):
        rows = [{"Component": COMPONENT_LABELS.get(k, k), "Points": v["points"], "Max": v["max"],
                 "Basis": v["basis"], "Why": v["why"]} for k, v in comps.items()]
        for p in bd.get("penalties", []):
            rows.append({"Component": f"Risk penalty: {p['label']}", "Points": p["points"], "Max": 0,
                         "Basis": "rule-based", "Why": "editorial / monetization risk"})
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch",
                         column_config={"Why": st.column_config.TextColumn(width="large")})
    flags = case.risk_flags or []
    with st.expander(f"Editorial risk indicators ({len(flags)})", expanded=bool(flags)):
        if not flags:
            st.caption("No risk keywords detected in source text. Still review the footage itself.")
        for f in flags:
            st.markdown(f"- **{f['label']}** - _{f['evidence']}_")
        st.caption("Keyword-based indicators from source text, not a legal or policy determination.")
    if case.ai_assessment:
        with st.expander("AI-generated estimate (not verified)"):
            a = case.ai_assessment
            st.caption(a.get("_label", "AI estimate") + f" - {a.get('_model', '')}")
            st.json({k: v for k, v in a.items() if not k.startswith("_")})


def render() -> None:
    st.title("Case Research")
    options = services.case_options(include_hidden=True)
    cid = common.selected_case_id(options, key="case_pick")
    if cid is None:
        st.info("No cases yet. Run research from the Overview page.")
        return
    case = services.load_case(cid)
    if case is None:
        st.warning("Case not found.")
        return

    head = st.columns([6, 1, 1, 1])
    with head[0]:
        st.markdown(f"## {case.headline}")
        common.show_badges((f"Score {case.score}", common.score_color(case.score)),
                           (case.bodycam_status, common.bodycam_color(case.bodycam_status)),
                           (case.youtube_status, common.youtube_color(case.youtube_status)))
    if head[1].button("Unsave" if case.saved else "Save", width="stretch"):
        services.set_case_flag(case.id, saved=not case.saved)
        st.rerun()
    if head[2].button("Unhide" if case.hidden else "Hide", width="stretch"):
        services.set_case_flag(case.id, hidden=not case.hidden)
        st.rerun()
    if head[3].button("Recompute", width="stretch", help="Re-run extraction and scoring for this case"):
        with session_scope() as s:
            c = s.get(Case, case.id)
            pipeline.recompute_case(c)
            pipeline.ensure_agency(s, c)
            pipeline.score(c)
        st.rerun()
    common.provenance_legend()

    left, middle, right = st.columns([1.1, 1, 1], gap="medium")
    with left:
        _left(case)
    with middle:
        _middle(case)
    with right:
        _right(case)
    _scoring(case)

    notes = st.text_area("Your notes", value=case.user_notes or "", key=f"notes_{case.id}")
    if notes != (case.user_notes or "") and st.button("Save notes"):
        services.set_case_flag(case.id, notes=notes)
        st.toast("Notes saved")
