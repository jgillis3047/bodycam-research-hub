"""Bodycam Research Hub - Streamlit entry point.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from bch import __version__, pipeline
from bch.db import init_db
from bch.ui import (agencies, case_research, common, competition, discover, footage, overview,
                    run_panel, settings_page, tracker)

st.set_page_config(page_title="Bodycam Research Hub", page_icon="🎥", layout="wide",
                   initial_sidebar_state="expanded")


@st.cache_resource
def _init() -> bool:
    init_db()
    return True


_ready = _init()
common.inject_css()

PAGES = {
    "overview": st.Page(overview.render, title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
    "discover": st.Page(discover.render, title="Discover Cases", icon=":material/travel_explore:", url_path="discover"),
    "case": st.Page(case_research.render, title="Case Research", icon=":material/find_in_page:", url_path="case"),
    "competition": st.Page(competition.render, title="YouTube Competition", icon=":material/smart_display:", url_path="competition"),
    "footage": st.Page(footage.render, title="Footage Request Research", icon=":material/gavel:", url_path="footage"),
    "tracker": st.Page(tracker.render, title="Request Tracker", icon=":material/checklist:", url_path="tracker"),
    "agencies": st.Page(agencies.render, title="Agencies and Sources", icon=":material/account_balance:", url_path="agencies"),
    "settings": st.Page(settings_page.render, title="Settings", icon=":material/settings:", url_path="settings"),
}
common.PAGES.update(PAGES)

nav = st.navigation(list(PAGES.values()))

with st.sidebar:
    st.markdown("### 🎥 Bodycam Research Hub")
    if nav.url_path not in ("", "overview"):
        run_panel.render("sidebar")
    elif pipeline.is_running():
        st.caption("Research is running...")
    st.caption(f"v{__version__} - all data stored locally")

nav.run()
