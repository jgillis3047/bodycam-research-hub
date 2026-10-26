"""Database engine, sessions, initialization and settings helpers."""
from __future__ import annotations

import copy
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base, Setting, TrackedChannel

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _set_sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")      # allows the scheduled job + UI at once
    cur.execute("PRAGMA busy_timeout=15000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_engine(path: str | Path | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None or path is not None:
        target = Path(path) if path else config.db_path()
        url = "sqlite://" if str(target) == ":memory:" else f"sqlite:///{target}"
        _engine = create_engine(url, future=True, connect_args={"check_same_thread": False})
        event.listen(_engine, "connect", _set_sqlite_pragmas)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def init_db(path: str | Path | None = None) -> Engine:
    """Create tables (idempotent) and seed defaults."""
    engine = get_engine(path)
    Base.metadata.create_all(engine)
    with session_scope() as s:
        if s.get(TrackedChannel, 1) is None and not s.scalars(select(TrackedChannel)).first():
            # Seeded as a handle only; the channel ID is resolved through the YouTube API.
            s.add(TrackedChannel(handle="@CodeBlueCam", enabled=True,
                                 last_status="Not yet resolved via YouTube API"))
    return engine


def SessionLocal() -> Session:  # noqa: N802 - factory style
    if _SessionLocal is None:
        get_engine()
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def get_setting(key: str, session: Session | None = None) -> Any:
    default = copy.deepcopy(config.DEFAULT_SETTINGS.get(key))
    own = session is None
    s = session or SessionLocal()
    try:
        row = s.get(Setting, key)
        if row is None:
            return default
        val = row.value
        if isinstance(default, dict) and isinstance(val, dict):
            merged = dict(default)
            merged.update(val)
            return merged
        return val
    finally:
        if own:
            s.close()


def set_setting(key: str, value: Any, session: Session | None = None) -> None:
    own = session is None
    s = session or SessionLocal()
    try:
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value))
        else:
            row.value = copy.deepcopy(value)
        if own:
            s.commit()
    finally:
        if own:
            s.close()


def all_settings() -> dict:
    return {k: get_setting(k) for k in config.DEFAULT_SETTINGS}
