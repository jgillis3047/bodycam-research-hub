"""Configuration: environment variables (.env) for secrets, SQLite-backed settings for everything else."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv, set_key
except ImportError:  # pragma: no cover - python-dotenv is in requirements
    load_dotenv = None
    set_key = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

if load_dotenv is not None and ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=False)


def _default_data_dir() -> Path:
    """Database + runtime files. On Windows these live in %LOCALAPPDATA% because SQLite files inside a
    OneDrive/Dropbox-synced folder can be corrupted by the sync client. Override with BCH_DATA_DIR."""
    custom = os.environ.get("BCH_DATA_DIR")
    if custom:
        return Path(custom)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "BodycamResearchHub"
    return PROJECT_ROOT / "data"


DATA_DIR = _default_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Keys that are secrets and live in .env (never in the database)
SECRET_KEYS = {
    "YOUTUBE_API_KEY": "YouTube Data API v3 key",
    "AI_PROVIDER": "Optional AI provider: anthropic or openai (blank = AI disabled)",
    "ANTHROPIC_API_KEY": "Optional Anthropic API key",
    "OPENAI_API_KEY": "Optional OpenAI API key",
    "AI_MODEL": "Optional model name override",
    "BRAVE_SEARCH_API_KEY": "Optional Brave Search API key (helps find agency websites)",
}

DEFAULT_STATES = ["Florida", "Ohio", "Wisconsin", "Texas", "Pennsylvania", "California"]

# Non-secret settings stored in SQLite (Setting table). These are the defaults.
DEFAULT_SETTINGS: dict = {
    "states": DEFAULT_STATES,
    "extra_locations": [],  # list of {"state":..,"county":..,"city":..}
    "lookback_days": 7,
    "categories": [
        "pursuit", "dui", "standoff", "robbery", "fleeing", "disorderly",
        "traffic_stop", "rescue", "bizarre", "confrontation", "call_911", "arrest",
    ],
    "enable_google_news": True,
    "enable_bing_news": True,
    "fetch_article_pages": True,
    "max_article_fetches_per_run": 60,
    "youtube_max_cases_per_run": 25,
    "youtube_results_per_query": 15,
    "youtube_queries_per_case": 1,
    "youtube_daily_quota_budget": 8000,
    "youtube_recheck_days": 3,
    "records_max_agencies_per_run": 15,
    "records_recheck_days": 30,
    "ai_max_cases_per_run": 20,
    "max_request_budget": 100.0,
    "research_time": "06:30",
    "request_contact": {
        "name": "", "organization": "", "email": "", "phone": "", "address": "",
    },
    "http_delay_seconds": 1.5,
    "contact_email_for_user_agent": "",
}


def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default) or default


def save_env(key: str, value: str) -> None:
    """Persist a secret to .env and the current process environment."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")
    if set_key is not None:
        set_key(str(ENV_PATH), key, value, quote_mode="never")
    else:  # minimal fallback
        lines = [ln for ln in ENV_PATH.read_text(encoding="utf-8").splitlines()
                 if not ln.startswith(f"{key}=")]
        lines.append(f"{key}={value}")
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def db_path() -> Path:
    custom = get_env("BCH_DB_PATH")
    return Path(custom) if custom else DATA_DIR / "bodycam_hub.sqlite3"
