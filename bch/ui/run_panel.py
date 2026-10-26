"""'Run Research Now' control with live progress (works across page reloads)."""
from __future__ import annotations

import streamlit as st

from .. import pipeline, services
from ..db import get_setting


@st.fragment(run_every=4)
def _live_progress() -> None:
    prog = pipeline.read_progress() or {}
    if pipeline.is_running():
        st.progress(float(prog.get("frac", 0.0)), text=prog.get("message", "Working..."))
        with st.expander("Live log", expanded=False):
            st.code("\n".join(prog.get("lines", [])[-25:]) or "Starting...", language=None)
    else:
        if st.session_state.get("_research_started"):
            st.session_state["_research_started"] = False
            st.success("Research run finished. Refreshing results...")
            st.rerun()


def render(location: str = "main") -> None:
    running = pipeline.is_running()
    last = get_setting("last_run") or {}
    cols = st.columns([1, 2]) if location == "main" else [st.container(), st.container()]
    with cols[0]:
        if st.button("Run Research Now", type="primary", disabled=running, key=f"run_{location}",
                     width="stretch", help="Searches news, YouTube and agency sites. Takes a few minutes."):
            services.launch_background_research()
            st.session_state["_research_started"] = True
            st.toast("Research started in the background. You can keep browsing.")
            st.rerun()
    with cols[1]:
        if last:
            st.caption(f"Last run: {last.get('at', '')[:16].replace('T', ' ')} UTC - {last.get('status')} "
                       f"({last.get('trigger')})")
        else:
            st.caption("No research runs yet.")
    if running or st.session_state.get("_research_started"):
        _live_progress()
