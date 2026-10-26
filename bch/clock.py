"""Single source of 'now' (naive UTC) so tests can freeze time."""
from __future__ import annotations

from datetime import date, datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    return datetime.now().date()
