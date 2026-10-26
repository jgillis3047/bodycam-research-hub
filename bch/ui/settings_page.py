"""Page 8 - Settings."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import delete

from .. import ai, analysis, config, net, services, youtube
from ..db import get_setting, session_scope, set_setting
from ..models import HttpCache


def _keys() -> None:
    st.subheader("API keys")
    st.caption(f"Stored in your local `.env` file ({config.ENV_PATH}). Never sent anywhere except the matching service.")
    with st.form("keys"):
        yt = st.text_input("YouTube Data API v3 key", config.get_env("YOUTUBE_API_KEY"), type="password",
                           help="Google Cloud Console > APIs & Services > enable 'YouTube Data API v3' > Credentials > API key")
        c = st.columns(3)
        provider = c[0].selectbox("AI provider (optional)", ["", "anthropic", "openai"],
                                  index=["", "anthropic", "openai"].index(config.get_env("AI_PROVIDER").lower())
                                  if config.get_env("AI_PROVIDER").lower() in ("", "anthropic", "openai") else 0)
        model = c[1].text_input("AI model (optional override)", config.get_env("AI_MODEL"),
                                placeholder=ai.DEFAULT_MODELS.get(provider or "anthropic"))
        anth = st.text_input("Anthropic API key", config.get_env("ANTHROPIC_API_KEY"), type="password")
        oai = st.text_input("OpenAI API key", config.get_env("OPENAI_API_KEY"), type="password")
        brave = st.text_input("Brave Search API key (optional - improves agency website discovery)",
                              config.get_env("BRAVE_SEARCH_API_KEY"), type="password")
        if st.form_submit_button("Save keys", type="primary"):
            for k, v in (("YOUTUBE_API_KEY", yt), ("AI_PROVIDER", provider), ("AI_MODEL", model),
                         ("ANTHROPIC_API_KEY", anth), ("OPENAI_API_KEY", oai), ("BRAVE_SEARCH_API_KEY", brave)):
                if v != config.get_env(k):
                    config.save_env(k, v.strip())
            st.success("Saved to .env")
    c = st.columns(3)
    if c[0].button("Test YouTube key", disabled=not youtube.is_configured()):
        try:
            st.success(f"YouTube API {youtube.test_key()}. Units used today (local count): "
                       f"{youtube.quota_used_today()}")
        except youtube.YouTubeError as exc:
            st.error(str(exc))
    c[1].caption(f"YouTube units used today (local count): {youtube.quota_used_today()} / "
                 f"{get_setting('youtube_daily_quota_budget')}")
    c[2].caption(f"AI: {'enabled (' + ai.provider() + ')' if ai.is_enabled() else 'not configured - rule-based only'}")


def _research() -> None:
    st.subheader("Research")
    with st.form("research_settings"):
        states_all = list(analysis.US_STATES)
        states = st.multiselect("States to research (in priority order)", states_all,
                                default=[s for s in get_setting("states") if s in states_all])
        c = st.columns(3)
        days = c[0].selectbox("Default lookback (days)", [7, 14, 30, 60, 90],
                              index=[7, 14, 30, 60, 90].index(get_setting("lookback_days"))
                              if get_setting("lookback_days") in [7, 14, 30, 60, 90] else 0)
        cats = st.multiselect("Incident types to search", list(analysis.CATEGORY_LABELS),
                              default=get_setting("categories"), format_func=analysis.CATEGORY_LABELS.get)
        g = c[1].checkbox("Google News RSS", get_setting("enable_google_news"))
        b = c[2].checkbox("Bing News RSS", get_setting("enable_bing_news"))
        c2 = st.columns(3)
        fetch = c2[0].checkbox("Read article pages for more detail (robots.txt respected)", get_setting("fetch_article_pages"))
        max_fetch = c2[1].number_input("Max article pages per run", 0, 500, int(get_setting("max_article_fetches_per_run")))
        delay = c2[2].number_input("Seconds between requests to the same site", 0.5, 10.0,
                                   float(get_setting("http_delay_seconds")), step=0.5)
        st.markdown("**YouTube**")
        c3 = st.columns(4)
        yt_cases = c3[0].number_input("Cases checked per run", 0, 100, int(get_setting("youtube_max_cases_per_run")),
                                      help="Each case uses ~100 units per query")
        yt_q = c3[1].number_input("Queries per case", 1, 3, int(get_setting("youtube_queries_per_case")))
        yt_n = c3[2].number_input("Results per query", 5, 50, int(get_setting("youtube_results_per_query")))
        yt_budget = c3[3].number_input("Daily unit budget", 500, 1_000_000, int(get_setting("youtube_daily_quota_budget")),
                                       help="Default Google quota is 10,000 units/day")
        st.markdown("**Records research & budget**")
        c4 = st.columns(3)
        ag_n = c4[0].number_input("Agencies researched per run", 0, 100, int(get_setting("records_max_agencies_per_run")))
        ag_re = c4[1].number_input("Re-research agencies after (days)", 1, 365, int(get_setting("records_recheck_days")))
        budget = c4[2].number_input("Maximum records request budget ($ per request)", 0.0, 10000.0,
                                    float(get_setting("max_request_budget")), step=5.0)
        ai_n = st.number_input("AI assessments per run (if AI configured)", 0, 200, int(get_setting("ai_max_cases_per_run")))
        if st.form_submit_button("Save research settings", type="primary"):
            for k, v in (("states", states), ("lookback_days", int(days)), ("categories", cats),
                         ("enable_google_news", g), ("enable_bing_news", b), ("fetch_article_pages", fetch),
                         ("max_article_fetches_per_run", int(max_fetch)), ("http_delay_seconds", float(delay)),
                         ("youtube_max_cases_per_run", int(yt_cases)), ("youtube_queries_per_case", int(yt_q)),
                         ("youtube_results_per_query", int(yt_n)), ("youtube_daily_quota_budget", int(yt_budget)),
                         ("records_max_agencies_per_run", int(ag_n)), ("records_recheck_days", int(ag_re)),
                         ("max_request_budget", float(budget)), ("ai_max_cases_per_run", int(ai_n))):
                set_setting(k, v)
            st.success("Saved")
    n_queries = len(get_setting("states")) * len(get_setting("categories"))
    st.caption(f"Current plan: {n_queries} news searches per enabled source per run "
               f"(+ extra locations and your feeds).")


def _contact() -> None:
    st.subheader("Your details for records requests")
    ctc = get_setting("request_contact") or {}
    with st.form("contact"):
        c = st.columns(2)
        name = c[0].text_input("Name", ctc.get("name", ""))
        org = c[1].text_input("Organization / channel name", ctc.get("organization", ""))
        email = c[0].text_input("E-mail", ctc.get("email", ""))
        phone = c[1].text_input("Phone", ctc.get("phone", ""))
        addr = st.text_area("Mailing address (needed for certified-mail requests)", ctc.get("address", ""))
        ua = st.checkbox("Include my e-mail in the app's web User-Agent (polite crawling practice)",
                         bool(get_setting("contact_email_for_user_agent")))
        if st.form_submit_button("Save details"):
            set_setting("request_contact", {"name": name, "organization": org, "email": email,
                                            "phone": phone, "address": addr})
            set_setting("contact_email_for_user_agent", email if ua else "")
            st.success("Saved")


def _schedule() -> None:
    st.subheader("Automatic daily research")
    t = get_setting("research_time") or "06:30"
    new_t = st.text_input("Daily run time (24h, HH:MM)", t)
    if new_t != t and st.button("Save time"):
        set_setting("research_time", new_t)
        st.rerun()
    root = config.PROJECT_ROOT
    st.markdown("Windows Task Scheduler runs research even when the dashboard is closed. "
                "In PowerShell, from the project folder, run:")
    st.code(f'powershell -ExecutionPolicy Bypass -File "{root / "scripts" / "register_daily_task.ps1"}" -Time {new_t}',
            language="powershell")
    st.caption("To remove it later: scripts\\unregister_daily_task.ps1. Logs are kept on the Overview page.")


def _maintenance() -> None:
    st.subheader("Data")
    c = st.columns(3)
    if c[0].button("Clear web cache"):
        with session_scope() as s:
            s.execute(delete(HttpCache))
        st.success("Cache cleared")
    df = services.cases_frame(include_hidden=True)
    c[1].download_button("Export all cases (CSV)", df.to_csv(index=False).encode("utf-8"),
                         file_name="cases.csv", mime="text/csv", disabled=df.empty)
    c[2].caption(f"Database: {config.db_path()}")
    net.configure()


def render() -> None:
    st.title("Settings")
    tabs = st.tabs(["API keys", "Research", "My details", "Schedule", "Data"])
    with tabs[0]:
        _keys()
    with tabs[1]:
        _research()
    with tabs[2]:
        _contact()
    with tabs[3]:
        _schedule()
    with tabs[4]:
        _maintenance()
