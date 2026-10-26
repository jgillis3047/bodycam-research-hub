"""Page 1 - Overview."""
from __future__ import annotations

import streamlit as st

from .. import ai, services, youtube
from ..db import get_setting
from . import common, run_panel


def render() -> None:
    st.title("Bodycam Research Hub")
    st.caption("Today's best bodycam opportunities across your selected states.")

    run_panel.render("main")

    m = services.metrics()
    c = st.columns(6)
    c[0].metric("Total cases", m["total"])
    c[1].metric("New this week", m["new_week"])
    c[2].metric("High priority (70+)", m["high_priority"])
    c[3].metric("Footage confirmed", m["confirmed_footage"], help="Footage released or mentioned in a source, or found on YouTube")
    c[4].metric("No YouTube match found", m["no_coverage"], help="Checked YouTube results contained no match. This is not proof it was never uploaded.")
    c[5].metric("Pending requests", m["pending_requests"])

    setup = []
    if not youtube.is_configured():
        setup.append("Add a **YouTube Data API key** in Settings to check existing coverage.")
    if not (get_setting("request_contact") or {}).get("name"):
        setup.append("Add your **name and e-mail** in Settings so generated records requests are ready to send.")
    if not ai.is_enabled():
        setup.append("Optional: add an **AI key** in Settings for AI summaries and interest estimates.")
    if setup:
        with st.container(border=True):
            st.markdown("**Setup checklist**")
            for s in setup:
                st.markdown(f"- {s}")

    st.subheader("Top opportunities")
    df = services.cases_frame()
    if df.empty:
        st.info("No cases yet. Click **Run Research Now** to search news sources for recent incidents.")
        return
    top = df.head(15)
    show = top[["id", "Score", "Incident", "State", "Incident Date", "Police Agency", "Bodycam Status",
                "YouTube Coverage", "Records Request Link", "Request Status"]]
    ev = st.dataframe(
        show, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        key="overview_table",
        column_config={
            "id": None,
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
            "Incident": st.column_config.TextColumn("Incident", width="large"),
            "Records Request Link": st.column_config.LinkColumn("Records Request", display_text="Open portal"),
            "Incident Date": st.column_config.DateColumn("Incident Date"),
        })
    rows = ev.selection.rows if ev and hasattr(ev, "selection") else []
    if rows:
        cid = int(show.iloc[rows[0]]["id"])
        if st.button("Open case research", type="primary"):
            common.open_case(cid)
    else:
        st.caption("Select a row to open its research page. Empty 'Records Request' = no verified portal yet.")

    st.subheader("Recent research runs")
    runs = services.latest_runs(5)
    if runs:
        st.dataframe([{
            "Started (UTC)": r.started_at.strftime("%Y-%m-%d %H:%M"), "Trigger": r.trigger, "Status": r.status,
            "New cases": (r.stats or {}).get("cases_new", 0), "Updated": (r.stats or {}).get("cases_updated", 0),
            "YouTube checks": (r.stats or {}).get("youtube_checked", 0),
            "Agencies researched": (r.stats or {}).get("agencies_researched", 0),
        } for r in runs], hide_index=True, width="stretch")
        with st.expander("Log of the latest run"):
            st.code(runs[0].log or "(empty)", language=None)
