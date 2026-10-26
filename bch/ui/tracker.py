"""Page 6 - Public Records Request Tracker."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from .. import services
from ..db import session_scope
from ..models import REQUEST_STATUSES, RecordsRequest


def _none(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _to_date(v):
    v = _none(v)
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    return v


def render() -> None:
    st.title("Request Tracker")
    df = services.requests_frame()

    today = date.today()
    if not df.empty:
        due = df[df["Follow-up"].apply(lambda d: _to_date(d) is not None and _to_date(d) <= today)
                 & ~df["Status"].isin(["Closed", "Denied", "Footage Received"])]
        c = st.columns(4)
        c[0].metric("Requests", len(df))
        c[1].metric("Open", int((~df["Status"].isin(["Closed", "Denied", "Footage Received"])).sum()))
        c[2].metric("Follow-ups due", len(due))
        c[3].metric("Total paid", f"${pd.to_numeric(df['Paid'], errors='coerce').fillna(0).sum():,.2f}")
        if len(due):
            st.warning("Follow-up due: " + "; ".join(f"{r.Agency} - {r.Incident[:50]}" for r in due.itertuples()))

    with st.expander("Add a request manually", expanded=df.empty):
        with st.form("new_req"):
            c = st.columns(2)
            agency = c[0].text_input("Agency")
            incident = c[1].text_input("Incident")
            status = c[0].selectbox("Status", REQUEST_STATUSES, index=1)
            submitted = c[1].date_input("Submitted date", value=None)
            tracking = c[0].text_input("Tracking number")
            method = c[1].selectbox("Submission method", ["", "Portal", "E-mail", "Mail", "Certified mail", "In person", "Phone"])
            notes = st.text_area("Notes")
            if st.form_submit_button("Add request") and (agency or incident):
                with session_scope() as s:
                    s.add(RecordsRequest(agency_name=agency, incident=incident, status=status, submitted_date=submitted,
                                         tracking_number=tracking or None, submission_method=method or None, notes=notes))
                st.rerun()

    if df.empty:
        st.info("No requests yet. Generate one from a case's Footage Request Research page.")
        return

    st.caption("Edit cells directly, then click **Save changes**.")
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key="tracker_editor", num_rows="fixed",
        disabled=["id", "case_id"],
        column_config={
            "id": None, "case_id": None,
            "Status": st.column_config.SelectboxColumn("Status", options=REQUEST_STATUSES, required=True),
            "Submitted": st.column_config.DateColumn("Submitted"),
            "Follow-up": st.column_config.DateColumn("Follow-up"),
            "Quoted Fee": st.column_config.NumberColumn("Quoted Fee", format="$%.2f", min_value=0),
            "Paid": st.column_config.NumberColumn("Paid", format="$%.2f", min_value=0),
            "Incident": st.column_config.TextColumn(width="large"),
            "Method": st.column_config.SelectboxColumn(
                "Method", options=["", "Portal", "E-mail", "Mail", "Certified mail", "In person", "Phone"]),
        })
    c = st.columns([1, 1, 3])
    if c[0].button("Save changes", type="primary"):
        with session_scope() as s:
            for row in edited.to_dict("records"):
                r = s.get(RecordsRequest, int(row["id"]))
                if r is None:
                    continue
                r.status = row["Status"]
                r.agency_name = _none(row["Agency"])
                r.incident = _none(row["Incident"])
                r.submitted_date = _to_date(row["Submitted"])
                r.tracking_number = _none(row["Tracking #"]) or None
                r.quoted_fee = float(row["Quoted Fee"]) if _none(row["Quoted Fee"]) is not None else None
                r.amount_paid = float(row["Paid"]) if _none(row["Paid"]) is not None else None
                r.follow_up_date = _to_date(row["Follow-up"])
                r.submission_method = _none(row["Method"]) or None
                r.response_info = _none(row["Response"])
                r.notes = _none(row["Notes"])
        st.success("Saved")
        st.rerun()
    c[1].download_button("Export CSV", df.drop(columns=["id"]).to_csv(index=False).encode("utf-8"),
                         file_name=f"records_requests_{today}.csv", mime="text/csv")

    with st.expander("View / delete a request"):
        pick = st.selectbox("Request", df["id"].tolist(),
                            format_func=lambda i: f"#{i} {df.loc[df['id'] == i, 'Agency'].iloc[0]} - "
                                                  f"{str(df.loc[df['id'] == i, 'Incident'].iloc[0])[:60]}")
        with session_scope() as s:
            r = s.get(RecordsRequest, int(pick))
            text = r.request_text if r else None
        if text:
            st.code(text, language=None)
        if st.button("Delete this request"):
            with session_scope() as s:
                r = s.get(RecordsRequest, int(pick))
                if r:
                    s.delete(r)
            st.rerun()
