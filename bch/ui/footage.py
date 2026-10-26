"""Page 5 - Footage Request Research: custodian, verification, law summary, request generator."""
from __future__ import annotations

from datetime import date

import streamlit as st
from sqlalchemy import select

from .. import ai, analysis, pipeline, records, services
from ..db import get_setting, session_scope
from ..models import Agency, Case, RecordsRequest, Verification
from ..request_writer import draft_request
from ..state_laws import law_for
from . import common


def _verify_buttons(ag: Agency) -> None:
    st.markdown("**Verification**")
    st.caption("Only links you verify (or that were found on the agency's own .gov site) appear as the "
               "'Open Records Request Portal' button.")
    for field, label, status_attr, value_attr in (
            ("website", "Website", "website_status", "website"),
            ("portal", "Request portal", "portal_status", "portal_url"),
            ("email", "Records e-mail", "email_status", "records_email")):
        val = getattr(ag, value_attr)
        status = getattr(ag, status_attr)
        cols = st.columns([3, 2, 1])
        cols[0].markdown(f"{label}: " + (f"`{val}`" if val else "_none_"))
        cols[1].markdown(common.badge(status, common.verification_color(status)), unsafe_allow_html=True)
        if val and status != Verification.USER_VERIFIED and cols[2].button("Mark verified", key=f"ver_{field}_{ag.id}"):
            with session_scope() as s:
                a = s.get(Agency, ag.id)
                setattr(a, status_attr, Verification.USER_VERIFIED)
                for c in a.cases:
                    pipeline.score(c)
            st.rerun()

    cands = [c for c in (ag.candidates or [])]
    if cands:
        with st.expander(f"Unverified candidates found ({len(cands)})"):
            for i, c in enumerate(cands):
                val = c.get("value") or c.get("url")
                cols = st.columns([4, 1])
                cols[0].markdown(f"**{c['field']}**: {val}  \n<span class='bch-muted'>{c.get('note', '')}</span>",
                                 unsafe_allow_html=True)
                if cols[1].button("Use + verify", key=f"cand_{ag.id}_{i}",
                                  help="Only click after opening the link and confirming it is the agency's official page"):
                    with session_scope() as s:
                        a = s.get(Agency, ag.id)
                        if c["field"] == "portal":
                            a.portal_url, a.portal_status = c["url"], Verification.USER_VERIFIED
                            a.portal_platform = records._platform_for(c["url"]) or "Agency web form/page"
                        elif c["field"] == "email":
                            a.records_email, a.email_status = c.get("value"), Verification.USER_VERIFIED
                        elif c["field"] == "website":
                            a.website, a.website_status = c["url"], Verification.USER_VERIFIED
                        for cc in a.cases:
                            pipeline.score(cc)
                    st.rerun()


def _edit_agency(ag: Agency) -> None:
    with st.form(f"agency_edit_{ag.id}"):
        st.markdown("**Enter or correct contact details yourself** (saved as 'Verified by you')")
        website = st.text_input("Official website", ag.website or "")
        portal = st.text_input("Public records request portal URL", ag.portal_url or "")
        email = st.text_input("Records e-mail", ag.records_email or "")
        phone = st.text_input("Records phone", ag.records_phone or "")
        fees = st.text_area("Published fees (paste from the agency's site)", ag.fee_info or "")
        fee_src = st.text_input("Fee source URL", ag.fee_source_url or "")
        notes = st.text_area("Notes", ag.notes or "")
        if st.form_submit_button("Save agency details"):
            with session_scope() as s:
                a = s.get(Agency, ag.id)
                if website.strip() != (a.website or ""):
                    a.website, a.website_status = website.strip() or None, Verification.USER_VERIFIED if website.strip() else Verification.NOT_FOUND
                if portal.strip() != (a.portal_url or ""):
                    a.portal_url = portal.strip() or None
                    a.portal_status = Verification.USER_VERIFIED if portal.strip() else Verification.NOT_FOUND
                    a.portal_platform = records._platform_for(portal) or ("Agency web form/page" if portal.strip() else None)
                if email.strip() != (a.records_email or ""):
                    a.records_email = email.strip() or None
                    a.email_status = Verification.USER_VERIFIED if email.strip() else Verification.NOT_FOUND
                a.records_phone = phone.strip() or None
                a.fee_info, a.fee_source_url = fees.strip() or None, fee_src.strip() or None
                a.notes = notes
                for c in a.cases:
                    pipeline.score(c)
            st.success("Saved")
            st.rerun()


def _assign_agency(case: Case) -> None:
    with st.expander("Wrong agency? Reassign"):
        with session_scope() as s:
            ags = s.scalars(select(Agency).order_by(Agency.state, Agency.name)).all()
            opts = {a.id: f"{a.name} ({a.state})" for a in ags}
        pick = st.selectbox("Existing agency", [0] + list(opts), format_func=lambda i: "-- choose --" if i == 0 else opts[i],
                            key=f"reassign_{case.id}")
        new_name = st.text_input("...or enter a new agency name", key=f"newag_{case.id}",
                                 placeholder="e.g. Pinellas County Sheriff's Office")
        if st.button("Reassign agency", key=f"reassign_btn_{case.id}"):
            with session_scope() as s:
                c = s.get(Case, case.id)
                if new_name.strip():
                    c.agency_name, c.agency_basis = new_name.strip(), "set by you"
                    pipeline.ensure_agency(s, c)
                elif pick:
                    a = s.get(Agency, pick)
                    c.agency, c.agency_name, c.agency_basis = a, a.name, "set by you"
                pipeline.score(c)
            st.rerun()


def _generator(case: Case, ag: Agency | None) -> None:
    st.subheader("Generate Records Request")
    contact = get_setting("request_contact") or {}
    if not contact.get("name"):
        st.warning("Add your contact details in Settings so they appear in the letter.")
    budget = float(get_setting("max_request_budget") or 0)
    c = st.columns(3)
    inc = {
        "bodycam": c[0].checkbox("Body-worn camera video", True, key="g_bwc"),
        "dashcam": c[0].checkbox("Dash / in-car video", True, key="g_dash"),
        "audio_911": c[1].checkbox("911 audio & dispatch", False, key="g_911"),
        "cad": c[1].checkbox("CAD call log", False, key="g_cad"),
        "incident_report": c[2].checkbox("Incident report / arrest affidavit", True, key="g_rep"),
        "photos": c[2].checkbox("Released scene photos", False, key="g_photo"),
    }
    d = st.columns(3)
    approx_time = d[0].text_input("Approximate time", key="g_time", placeholder="e.g. 10:30 PM")
    report_no = d[1].text_input("Report / case number", key="g_report")
    names = d[2].text_input("Person(s) recorded (comma separated)", ", ".join(case.suspect_names or []), key="g_names")
    incident_date = st.date_input("Incident date", case.incident_date or case.first_published.date()
                                  if (case.incident_date or case.first_published) else date.today(), key="g_date")
    if not case.incident_date:
        st.caption(":orange[Incident date was not stated in the sources - confirm it before sending.]")

    payload = {
        "headline": case.headline, "state": case.state, "city": case.city, "county": case.county,
        "incident_date": incident_date, "location_text": case.city, "suspect_names": case.suspect_names,
        "sources": [a.url for a in case.articles if not a.url.startswith("https://news.google.com")][:3]
                   or [a.url for a in case.articles][:2],
    }
    if st.button("Generate request", type="primary") or st.session_state.pop("autogen", False):
        st.session_state["draft_text"] = draft_request(
            case=payload, agency_name=ag.name if ag else case.agency_name, contact=contact, budget=budget,
            include=inc, approx_time=approx_time, report_number=report_no,
            subject_names=[n.strip() for n in names.split(",") if n.strip()])
        st.session_state["draft_case"] = case.id
    text = st.session_state.get("draft_text") if st.session_state.get("draft_case") == case.id else None
    if not text:
        return
    if ai.is_enabled() and st.button("Polish wording with AI (keeps all facts)"):
        with st.spinner("Polishing..."):
            try:
                st.session_state["draft_text"] = ai.polish_request(text)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"AI polish failed: {exc}")
    edited = st.text_area("Draft (edit freely)", text, height=420, key=f"draft_edit_{case.id}")
    st.caption("Copy with the icon in the top-right of the box below. Nothing is submitted automatically.")
    st.code(edited, language=None)
    if "[FILL IN" in edited:
        st.warning("The draft still contains [FILL IN: ...] placeholders.")
    cols = st.columns(3)
    cols[0].download_button("Download .txt", edited, file_name=f"records_request_case{case.id}.txt", width="stretch")
    email = records.trusted_email(ag)
    if email:
        import urllib.parse
        mailto = f"mailto:{email}?subject={urllib.parse.quote('Public records request: ' + case.headline[:80])}"
        cols[1].link_button("Open e-mail draft", mailto, width="stretch",
                            help="Opens your mail app with the address and subject. Paste the letter yourself.")
    if cols[2].button("Save to tracker as 'Ready to Request'", width="stretch"):
        with session_scope() as s:
            s.add(RecordsRequest(case_id=case.id, agency_id=ag.id if ag else None,
                                 agency_name=ag.name if ag else case.agency_name, incident=case.headline[:500],
                                 status="Ready to Request", request_text=edited,
                                 submission_method="Portal" if records.trusted_portal(ag) else ("E-mail" if email else None)))
        st.success("Added to Request Tracker.")


def render() -> None:
    st.title("Footage Request Research")
    options = services.case_options(include_hidden=True)
    cid = common.selected_case_id(options, key="footage_pick")
    if cid is None:
        st.info("No cases yet.")
        return
    case = services.load_case(cid)
    ag = case.agency
    law = law_for(case.state)

    top = st.columns([2, 1])
    with top[0]:
        st.markdown(f"### {case.headline}")
        st.caption(f"{case.city or ''} {case.county or ''} {case.state or ''} - incident date: "
                   f"{case.incident_date or 'unknown'} ({case.incident_date_basis})")
    with top[1]:
        portal = records.trusted_portal(ag)
        if portal:
            st.link_button("Open Records Request Portal", portal, type="primary", width="stretch")
        else:
            st.error("No verified request portal yet")

    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("Records custodian")
        if ag is None:
            st.warning("No agency identified in the sources.")
            _assign_agency(case)
        else:
            st.markdown(f"**{ag.name}** ({ag.agency_type or 'agency'}, {ag.state or '?'})")
            st.caption(f"Agency basis: {case.agency_basis}. Last researched: "
                       f"{ag.last_researched_at:%Y-%m-%d %H:%M} UTC" if ag.last_researched_at else
                       f"Agency basis: {case.agency_basis}. Not researched yet.")
            if st.button("Research this agency now", type="secondary"):
                with st.spinner("Checking the agency's official website (robots.txt respected)..."):
                    res = pipeline.research_agency_by_id(ag.id)
                st.code("\n".join(res.log) or "done", language=None)
                st.rerun()
            _verify_buttons(ag)
            if ag.records_page_url:
                st.markdown(f"Records page: [{ag.records_page_url}]({ag.records_page_url})")
            if ag.fee_info:
                st.markdown(f"**Published fees:** {ag.fee_info}")
                if ag.fee_source_url:
                    st.caption(f"[source]({ag.fee_source_url})")
            ev = ag.evidence or []
            if ev:
                with st.expander("Evidence for each finding"):
                    for e in ev:
                        st.markdown(f"- **{e['field']}**: {e['snippet'][:250]} ([page]({e['url']}))")
            if ag.research_log:
                with st.expander("Research log"):
                    st.code(ag.research_log, language=None)
            if ag.request_instructions:
                st.markdown("**Request instructions**")
                st.markdown(ag.request_instructions.replace("\n", "  \n"))
            _edit_agency(ag)
            _assign_agency(case)

    with right:
        st.subheader("State law")
        st.markdown(f"**{law['law_name']}** - {law['citation']}")
        if law.get("statute_url"):
            st.markdown(f"[Official reference]({law['statute_url']})")
        st.markdown(f"**Response time:** {law['response_time']}")
        if law.get("special_requirements"):
            st.markdown("**Required in this state:**")
            for r in law["special_requirements"]:
                st.markdown(f"- :orange[{r}]")
        if law.get("request_window_days") and (case.incident_date or case.first_published):
            ref = case.incident_date or case.first_published.date()
            left_days = law["request_window_days"] - (date.today() - ref).days
            if left_days < 0:
                st.error(f"The {law['request_window_days']}-day window appears to have passed ({-left_days} days ago).")
            else:
                st.warning(f"About {left_days} day(s) left in the {law['request_window_days']}-day window.")
        st.markdown("**Bodycam rules**")
        for r in law["bodycam_rules"]:
            st.markdown(f"- {r}")
        st.markdown(f"**Fees:** {law['fees']}")
        for t in law.get("tips", []):
            st.caption(f"Tip: {t}")
        if law.get("sources"):
            st.caption("Checked against: " + ", ".join(f"[{i + 1}]({u})" for i, u in enumerate(law["sources"])))
        st.caption("Informational only - not legal advice. Confirm current law and the agency's procedure.")

    st.divider()
    _generator(case, ag)
