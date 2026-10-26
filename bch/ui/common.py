"""Shared UI helpers: styling, badges, navigation registry."""
from __future__ import annotations

import html

import streamlit as st

from ..models import BodycamStatus, Verification, YouTubeStatus

PAGES: dict = {}  # filled by app.py: key -> st.Page

CSS = """
<style>
:root { --bch-green:#22c55e; --bch-amber:#f59e0b; --bch-red:#ef4444; --bch-blue:#3b82f6;
        --bch-grey:#6b7280; --bch-purple:#a855f7; }
.block-container { padding-top: 1.6rem; max-width: 1600px; }
.bch-badge { display:inline-block; padding:2px 9px; border-radius:999px; font-size:0.78rem; font-weight:600;
             margin:0 4px 4px 0; border:1px solid rgba(255,255,255,0.12); white-space:nowrap; }
.bch-green  { background:rgba(34,197,94,0.15);  color:#4ade80; }
.bch-amber  { background:rgba(245,158,11,0.15); color:#fbbf24; }
.bch-red    { background:rgba(239,68,68,0.15);  color:#f87171; }
.bch-blue   { background:rgba(59,130,246,0.15); color:#60a5fa; }
.bch-grey   { background:rgba(107,114,128,0.2); color:#cbd5e1; }
.bch-purple { background:rgba(168,85,247,0.15); color:#c084fc; }
.bch-score  { font-size:2.1rem; font-weight:800; line-height:1; }
.bch-muted  { color:#94a3b8; font-size:0.85rem; }
.bch-card   { border:1px solid rgba(148,163,184,0.18); border-radius:12px; padding:14px 16px;
              background:rgba(15,23,42,0.35); margin-bottom:12px; }
.bch-acq    { border:1px solid rgba(34,197,94,0.45); border-radius:12px; padding:14px 16px;
              background:rgba(34,197,94,0.06); margin-bottom:12px; }
.bch-legend span { margin-right:10px; }
div[data-testid="stMetricValue"] { font-size: 1.9rem; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def badge(text: str, color: str = "grey") -> str:
    return f'<span class="bch-badge bch-{color}">{html.escape(str(text))}</span>'


def show_badges(*items: tuple[str, str]) -> None:
    st.markdown(" ".join(badge(t, c) for t, c in items), unsafe_allow_html=True)


def score_color(score: int) -> str:
    return "green" if score >= 70 else "amber" if score >= 45 else "grey"


def bodycam_color(status: str) -> str:
    return {BodycamStatus.RELEASED: "green", BodycamStatus.YOUTUBE_FOUND: "red",
            BodycamStatus.MENTIONED: "green", BodycamStatus.LIKELY: "purple"}.get(status, "grey")


def youtube_color(status: str) -> str:
    return {YouTubeStatus.FOOTAGE: "red", YouTubeStatus.NEWS: "amber", YouTubeStatus.COMMENTARY: "amber",
            YouTubeStatus.RELATED_OTHER: "green", YouTubeStatus.NONE_FOUND: "green"}.get(status, "grey")


def verification_color(status: str) -> str:
    return {Verification.USER_VERIFIED: "green", Verification.OFFICIAL_SITE: "green",
            Verification.UNVERIFIED: "amber", Verification.NOT_FOUND: "red"}.get(status, "grey")


def provenance_legend() -> None:
    st.markdown(
        '<div class="bch-legend bch-muted">'
        + badge("Verified / stated in source", "green")
        + badge("Likely but unconfirmed", "amber")
        + badge("AI / rule-based estimate", "purple")
        + badge("Missing / not checked", "grey")
        + "</div>", unsafe_allow_html=True)


def basis_color(basis: str | None) -> str:
    if not basis:
        return "grey"
    b = basis.lower()
    if "stated in source" in b or "named in source" in b or "dateline" in b:
        return "green"
    if "estimate" in b or "ai" == b[:2]:
        return "purple"
    if "unknown" in b or "not stated" in b:
        return "grey"
    return "amber"


def open_case(case_id: int) -> None:
    st.session_state["case_id"] = int(case_id)
    page = PAGES.get("case")
    if page is not None:
        st.switch_page(page)


def selected_case_id(options: list[tuple[int, str]], key: str) -> int | None:
    """Case picker that remembers the last case opened anywhere in the app."""
    if not options:
        return None
    ids = [o[0] for o in options]
    labels = {o[0]: o[1] for o in options}
    current = st.session_state.get("case_id")
    qp = st.query_params.get("case")
    if qp and str(qp).isdigit() and int(qp) in ids and current is None:
        current = int(qp)
    index = ids.index(current) if current in ids else 0
    chosen = st.selectbox("Case", ids, index=index, format_func=lambda i: labels[i], key=key)
    st.session_state["case_id"] = chosen
    return chosen


def fmt_views(n: int | None) -> str:
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
