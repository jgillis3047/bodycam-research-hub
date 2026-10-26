"""Page 7 - Agencies and Sources."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st
from sqlalchemy import select

from .. import analysis, discovery, feeds, net, pipeline, services
from ..db import get_setting, session_scope, set_setting
from ..models import Agency, Source, Verification
from . import common


def _agencies_tab() -> None:
    df = services.agencies_frame()
    st.caption("Agencies are created automatically from cases. Research fills in contact details; "
               "you can verify or correct them on the Footage Request Research page.")
    with st.expander("Add an agency manually"):
        with st.form("add_agency"):
            c = st.columns(3)
            name = c[0].text_input("Agency name", placeholder="Tampa Police Department")
            state = c[1].selectbox("State", list(analysis.US_STATES))
            county = c[2].text_input("County (for sheriffs)")
            city = c[0].text_input("City")
            website = c[1].text_input("Official website")
            portal = c[2].text_input("Records portal URL")
            email = c[0].text_input("Records e-mail")
            if st.form_submit_button("Add agency") and name.strip():
                with session_scope() as s:
                    norm = analysis.normalize_agency(name)
                    if s.scalars(select(Agency).where(Agency.normalized_name == norm, Agency.state == state)).first():
                        st.warning("That agency already exists.")
                    else:
                        s.add(Agency(
                            name=name.strip(), normalized_name=norm, state=state, county=county or None,
                            city=city or None, agency_type=analysis.classify_agency(name),
                            website=website or None,
                            website_status=Verification.USER_VERIFIED if website else Verification.NOT_RESEARCHED,
                            portal_url=portal or None,
                            portal_status=Verification.USER_VERIFIED if portal else Verification.NOT_RESEARCHED,
                            records_email=email or None,
                            email_status=Verification.USER_VERIFIED if email else Verification.NOT_RESEARCHED,
                            candidates=[], evidence=[]))
                        st.success("Added")
    if df.empty:
        st.info("No agencies yet.")
        return
    ev = st.dataframe(df, hide_index=True, width="stretch", height=420, on_select="rerun",
                      selection_mode="single-row", key="agency_table",
                      column_config={"id": None,
                                     "Website": st.column_config.LinkColumn("Website"),
                                     "Portal": st.column_config.LinkColumn("Portal")})
    rows = ev.selection.rows if ev and hasattr(ev, "selection") else []
    if rows:
        aid = int(df.iloc[rows[0]]["id"])
        c = st.columns(3)
        if c[0].button("Research selected agency now", type="primary"):
            with st.spinner("Researching..."):
                res = pipeline.research_agency_by_id(aid)
            st.code("\n".join(res.log), language=None)
        if c[1].button("Delete agency"):
            with session_scope() as s:
                a = s.get(Agency, aid)
                for case in a.cases:
                    case.agency = None
                s.delete(a)
            st.rerun()


def _sources_tab() -> None:
    st.markdown("**Built-in sources** (configured in Settings): Google News RSS and Bing News RSS searches "
                "for each selected state x incident type, plus your extra locations below.")
    st.markdown("**Your feeds** - add police/sheriff newsroom RSS feeds, local TV station feeds, or any RSS/Atom feed. "
                "Official agency feeds count as high-reliability sources.")
    with st.form("add_feed"):
        c = st.columns([2, 3, 1, 1])
        name = c[0].text_input("Name", placeholder="Polk County Sheriff newsroom")
        url = c[1].text_input("Feed URL (RSS/Atom)")
        state = c[2].selectbox("State", [""] + list(analysis.US_STATES))
        official = c[3].checkbox("Official agency", value=False)
        if st.form_submit_button("Test & add feed") and url.strip():
            try:
                items = discovery.fetch_configured_feed(url.strip(), name or url, state or None, official)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not read this feed: {exc}")
            else:
                if not items:
                    st.error("The URL loaded but no feed items were found. Is it an RSS/Atom feed?")
                else:
                    with session_scope() as s:
                        if s.scalars(select(Source).where(Source.url == url.strip())).first():
                            st.warning("Feed already added.")
                        else:
                            s.add(Source(name=name or net.domain_of(url), url=url.strip(), state=state or None,
                                         is_official=official, last_status=f"OK - {len(items)} items"))
                            st.success(f"Added. Latest item: {items[0].title}")

    with st.expander("Find feeds on a web page"):
        page = st.text_input("Agency newsroom / news site page URL", key="feed_find_url")
        if st.button("Look for RSS feeds") and page.strip():
            try:
                resp = net.get(page.strip(), ttl=timedelta(hours=6))
                found = feeds.find_feed_links(resp.text, resp.url)
                if found:
                    st.write("Feeds advertised on that page (test one by adding it above):")
                    for f in found:
                        st.code(f, language=None)
                else:
                    st.info("No feed links found on that page.")
            except net.AccessRestricted as exc:
                st.warning(f"Not fetched: {exc}")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

    with session_scope() as s:
        srcs = s.scalars(select(Source).order_by(Source.name)).all()
    if srcs:
        for src in srcs:
            c = st.columns([3, 4, 1, 1, 1])
            c[0].markdown(f"**{src.name}** {common.badge('official', 'green') if src.is_official else ''}",
                          unsafe_allow_html=True)
            c[1].caption(f"{src.url}  \n{src.last_status or 'never fetched'}")
            c[2].caption(src.state or "")
            if c[3].button("Disable" if src.enabled else "Enable", key=f"src_t_{src.id}"):
                with session_scope() as s:
                    x = s.get(Source, src.id)
                    x.enabled = not x.enabled
                st.rerun()
            if c[4].button("Delete", key=f"src_d_{src.id}"):
                with session_scope() as s:
                    s.delete(s.get(Source, src.id))
                st.rerun()

    st.divider()
    st.markdown("**Extra locations** - add counties, cities or specific agencies to search (any state).")
    locs = get_setting("extra_locations") or []
    with st.form("add_loc"):
        c = st.columns(4)
        state = c[0].selectbox("State", list(analysis.US_STATES), key="loc_state")
        county = c[1].text_input("County", key="loc_county")
        city = c[2].text_input("City", key="loc_city")
        agency = c[3].text_input("Agency (optional)", key="loc_agency")
        if st.form_submit_button("Add location") and (county or city or agency):
            locs.append({"state": state, "county": county.strip(), "city": city.strip(), "agency": agency.strip()})
            set_setting("extra_locations", locs)
            st.rerun()
    for i, loc in enumerate(locs):
        c = st.columns([5, 1])
        c[0].markdown(" / ".join(x for x in [loc.get("state"), loc.get("county"), loc.get("city"), loc.get("agency")] if x))
        if c[1].button("Remove", key=f"loc_rm_{i}"):
            locs.pop(i)
            set_setting("extra_locations", locs)
            st.rerun()


def render() -> None:
    st.title("Agencies and Sources")
    t1, t2 = st.tabs(["Agencies", "News & police sources"])
    with t1:
        _agencies_tab()
    with t2:
        _sources_tab()
