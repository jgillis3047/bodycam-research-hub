"""Page 2 - Discover Cases: searchable, sortable, filterable case table."""
from __future__ import annotations

import streamlit as st

from .. import services
from ..analysis import CATEGORY_LABELS
from ..db import get_setting
from ..models import REQUEST_STATUSES, BodycamStatus, YouTubeStatus
from . import common


def _filters(df) -> dict:
    states_available = sorted(set(df["State"].dropna()) - {""}) if not df.empty else []
    default_days = int(get_setting("lookback_days") or 7)
    day_opts = [7, 14, 30, 60, 90]
    with st.container(border=True):
        r1 = st.columns([2, 1, 2, 2])
        search = r1[0].text_input("Search incidents / agencies", key="f_search", placeholder="e.g. chase, Tampa")
        days = r1[1].selectbox("Past days", day_opts, index=day_opts.index(default_days) if default_days in day_opts else 0,
                               key="f_days", help="Uses the incident date when known, otherwise the first report date")
        states = r1[2].multiselect("State", states_available, key="f_states")
        place = r1[3].text_input("County or city contains", key="f_place")
        r2 = st.columns([2, 1, 2, 2])
        types = r2[0].multiselect("Incident type", list(CATEGORY_LABELS), format_func=CATEGORY_LABELS.get, key="f_types")
        min_score = r2[1].slider("Min score", 0, 100, 0, step=5, key="f_score")
        bodycam = r2[2].multiselect("Bodycam status", BodycamStatus.ALL, key="f_bodycam")
        yt = r2[3].multiselect("YouTube coverage", YouTubeStatus.ALL, key="f_yt")
        r3 = st.columns([2, 2, 1, 1, 1])
        req = r3[0].multiselect("Request status", ["Not started"] + REQUEST_STATUSES, key="f_req")
        budget = float(get_setting("max_request_budget") or 100)
        max_cost = r3[1].slider("Max expected footage cost ($)", 0, 1000, min(1000, int(max(budget, 50))), step=25, key="f_cost")
        include_unknown = r3[2].checkbox("Include unknown cost", True, key="f_cost_unknown")
        saved_only = r3[3].checkbox("Saved only", False, key="f_saved")
        show_hidden = r3[4].checkbox("Show hidden", False, key="f_hidden")
    return {"search": search, "days": days, "states": states, "place": place, "types": types,
            "min_score": min_score, "bodycam": bodycam, "youtube": yt, "request": req, "max_cost": max_cost,
            "include_unknown_cost": include_unknown, "saved_only": saved_only, "show_hidden": show_hidden}


def render() -> None:
    st.title("Discover Cases")
    common.provenance_legend()
    show_hidden = st.session_state.get("f_hidden", False)
    df = services.cases_frame(include_hidden=show_hidden)
    f = _filters(df)
    view = services.apply_filters(df, f)
    st.caption(f"{len(view)} of {len(df)} cases match. Click a column header to sort. Select a row for actions.")

    cols = ["id", "Score", "Incident", "State", "Incident Date", "Police Agency", "Bodycam Status",
            "YouTube Coverage", "Records Request Link", "Request Status", "Type", "City", "County",
            "First Reported", "Date basis", "Portal", "Est. Cost", "Sources", "Risks", "Saved"]
    ev = st.dataframe(
        view[cols], hide_index=True, width="stretch", height=560, on_select="rerun",
        selection_mode="single-row", key="discover_table",
        column_config={
            "id": None,
            "Score": st.column_config.ProgressColumn("Opportunity Score", min_value=0, max_value=100, format="%d"),
            "Incident": st.column_config.TextColumn("Incident", width="large"),
            "Incident Date": st.column_config.DateColumn("Incident Date"),
            "First Reported": st.column_config.DateColumn("First Reported"),
            "Records Request Link": st.column_config.LinkColumn(
                "Records Request Link", display_text="Open Records Request Portal",
                help="Only verified official portals are linked. Blank = not verified yet."),
            "Est. Cost": st.column_config.NumberColumn("Est. Cost", format="$%.0f",
                                                       help="Estimate from published fee info, when available"),
            "Saved": st.column_config.CheckboxColumn("Saved"),
        })

    rows = ev.selection.rows if ev and hasattr(ev, "selection") else []
    if not rows:
        return
    row = view[cols].iloc[rows[0]]
    cid = int(row["id"])
    with st.container(border=True):
        st.markdown(f"**{row['Incident']}**")
        a = st.columns(4)
        if a[0].button("Open case research", type="primary", width="stretch"):
            common.open_case(cid)
        if a[1].button("Unsave" if row["Saved"] else "Save case", width="stretch"):
            services.set_case_flag(cid, saved=not bool(row["Saved"]))
            st.rerun()
        is_hidden = bool(df.loc[df["id"] == cid, "Hidden"].iloc[0]) if "Hidden" in df else False
        if a[2].button("Unhide" if is_hidden else "Hide (not relevant)", width="stretch"):
            services.set_case_flag(cid, hidden=not is_hidden)
            st.rerun()
        if a[3].button("Footage request research", width="stretch"):
            st.session_state["case_id"] = cid
            st.switch_page(common.PAGES["footage"])
