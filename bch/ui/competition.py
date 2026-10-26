"""Page 4 - YouTube Competition: track what competitor channels upload."""
from __future__ import annotations

from .. import clock
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .. import pipeline, youtube
from ..analysis import CATEGORY_LABELS
from ..db import session_scope
from ..models import Case, ChannelVideo, TrackedChannel
from . import common


def _refresh() -> None:
    with session_scope() as s:
        rl = pipeline.RunLog(None)
        n = pipeline.refresh_competition(s, rl)
    st.success(f"Updated {n} videos. " + " ".join(rl.lines[-3:]))


def render() -> None:
    st.title("YouTube Competition")
    if not youtube.is_configured():
        st.warning("Add a YouTube Data API key in Settings to track channels.")

    with st.container(border=True):
        c = st.columns([3, 1, 1])
        new = c[0].text_input("Add a channel (@handle, channel URL, or UC... id)", key="new_channel",
                              placeholder="@SomeChannel")
        if c[1].button("Add channel", width="stretch") and new.strip():
            with session_scope() as s:
                if not s.scalars(select(TrackedChannel).where(TrackedChannel.handle == new.strip())).first():
                    s.add(TrackedChannel(handle=new.strip(), enabled=True))
            st.rerun()
        if c[2].button("Refresh uploads", type="primary", width="stretch", disabled=not youtube.is_configured(),
                       help="~3 API units per channel"):
            with st.spinner("Fetching recent uploads..."):
                try:
                    _refresh()
                except youtube.YouTubeError as exc:
                    st.error(str(exc))

    with session_scope() as s:
        chans = s.scalars(select(TrackedChannel).options(selectinload(TrackedChannel.videos))
                          .order_by(TrackedChannel.id)).all()
        cases = {c.id: c.headline for c in s.scalars(select(Case)).all()}
    if not chans:
        st.info("No channels tracked yet.")
        return

    st.subheader("Channels")
    for ch in chans:
        vids = sorted(ch.videos, key=lambda v: v.published_at or datetime.min, reverse=True)
        last30 = [v for v in vids if v.published_at and v.published_at >= clock.utcnow() - timedelta(days=30)]
        with st.container(border=True):
            cols = st.columns([3, 1, 1, 1, 1, 1])
            title = ch.title or ch.handle
            link = f"https://www.youtube.com/channel/{ch.channel_id}" if ch.channel_id else None
            cols[0].markdown(f"**[{title}]({link})**" if link else f"**{title}**")
            cols[0].caption(f"{ch.handle} - {ch.last_status or ''}")
            cols[1].metric("Subscribers", common.fmt_views(ch.subscriber_count))
            cols[2].metric("Uploads (30d)", len(last30))
            cols[3].metric("Avg views (30d)", common.fmt_views(int(sum(v.view_count or 0 for v in last30) / len(last30)) if last30 else None))
            cols[4].metric("Matches your cases", sum(1 for v in vids if v.matched_case_id))
            if cols[5].button("Pause" if ch.enabled else "Resume", key=f"tog_{ch.id}"):
                with session_scope() as s:
                    c = s.get(TrackedChannel, ch.id)
                    c.enabled = not c.enabled
                st.rerun()
            if cols[5].button("Remove", key=f"rm_{ch.id}"):
                with session_scope() as s:
                    s.delete(s.get(TrackedChannel, ch.id))
                st.rerun()

    rows = []
    for ch in chans:
        for v in ch.videos:
            rows.append({
                "Thumbnail": v.thumbnail_url, "Title": v.title, "Channel": ch.title or ch.handle,
                "Published": v.published_at, "Views": v.view_count, "Length": youtube.iso_duration_to_text(v.duration),
                "State": v.detected_state or "", "Type": CATEGORY_LABELS.get(v.detected_category or "", ""),
                "Matches case": cases.get(v.matched_case_id, "") if v.matched_case_id else "",
                "Link": v.url,
            })
    if not rows:
        st.info("No uploads loaded yet. Click **Refresh uploads**.")
        return
    df = pd.DataFrame(rows).sort_values("Published", ascending=False)

    st.subheader("Publishing activity (uploads per week)")
    act = df.dropna(subset=["Published"]).copy()
    if not act.empty:
        act["Week"] = pd.to_datetime(act["Published"]).dt.to_period("W").dt.start_time
        pivot = act.groupby(["Week", "Channel"]).size().unstack(fill_value=0)
        st.bar_chart(pivot)
    c = st.columns(2)
    with c[0]:
        st.markdown("**Incident types covered**")
        types = df[df["Type"] != ""]["Type"].value_counts()
        st.bar_chart(types) if not types.empty else st.caption("No types detected")
    with c[1]:
        st.markdown("**States covered (from titles/descriptions)**")
        states = df[df["State"] != ""]["State"].value_counts()
        st.bar_chart(states) if not states.empty else st.caption("No states detected")

    st.subheader("Recent uploads")
    chan_filter = st.multiselect("Channels", sorted(df["Channel"].unique()), key="comp_ch")
    view = df[df["Channel"].isin(chan_filter)] if chan_filter else df
    st.dataframe(view, hide_index=True, width="stretch", height=520, column_config={
        "Thumbnail": st.column_config.ImageColumn("Thumbnail", width="small"),
        "Title": st.column_config.TextColumn(width="large"),
        "Views": st.column_config.NumberColumn(format="%d"),
        "Link": st.column_config.LinkColumn("Link", display_text="Watch"),
        "Published": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
    })
