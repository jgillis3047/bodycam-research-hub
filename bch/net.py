"""Polite HTTP layer: robots.txt, per-domain rate limiting, caching, and access-restriction detection.

Rules this module enforces:
* Every HTML page fetch checks robots.txt for our user agent first.
* Requests to the same domain are spaced out (default 1.5 s).
* Responses are cached in SQLite to avoid duplicate requests.
* CAPTCHA / login / paywall / 401 / 403 / 429 responses are treated as "access restricted":
  we record it and move on. Nothing here tries to get around them.
"""
from __future__ import annotations

from . import clock
import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from . import __version__

log = logging.getLogger(__name__)

_BASE_UA = f"BodycamResearchHub/{__version__} (personal news-research tool; respects robots.txt)"
TIMEOUT = 20

_lock = threading.Lock()
_last_hit: dict[str, float] = {}
_robots: dict[str, RobotFileParser | None] = {}
_session: requests.Session | None = None
_delay_seconds = 1.5
_contact = ""

RESTRICTION_MARKERS = (
    "captcha", "g-recaptcha", "hcaptcha", "cf-challenge", "are you a robot",
    "verify you are human", "access denied", "subscribe to continue",
    "this content is for subscribers",
)


BLOCK_TITLES = ("just a moment", "attention required", "access denied", "are you a robot", "security check",
                "verify you are human", "please verify", "captcha", "403 forbidden", "subscribe to read")


def looks_blocked(html_text: str) -> bool:
    """True for challenge/paywall pages. A normal page that merely embeds a reCAPTCHA contact form is NOT blocked."""
    import re as _re
    head = html_text[:30000]
    m = _re.search(r"<title[^>]*>(.*?)</title>", head, _re.I | _re.S)
    title = (m.group(1) if m else "").strip().lower()
    if any(t in title for t in BLOCK_TITLES):
        return True
    visible = _re.sub(r"(?s)<(script|style|noscript)[^>]*>.*?</\1>", " ", head)
    visible = _re.sub(r"<[^>]+>", " ", visible)
    visible = _re.sub(r"\s+", " ", visible).strip().lower()
    return len(visible) < 1500 and any(mk in head.lower() for mk in RESTRICTION_MARKERS)


class AccessRestricted(Exception):
    """Raised when a site blocks automated access (robots, CAPTCHA, auth, paywall, rate limit)."""


@dataclass
class Response:
    url: str
    status: int
    text: str
    from_cache: bool = False


def configure(delay_seconds: float | None = None, contact_email: str | None = None) -> None:
    global _delay_seconds, _contact, _session
    if delay_seconds is not None:
        _delay_seconds = max(0.5, float(delay_seconds))
    if contact_email is not None and contact_email != _contact:
        _contact = contact_email
        if _session is not None:
            _session.headers["User-Agent"] = user_agent()


def user_agent() -> str:
    return f"{_BASE_UA}; contact: {_contact}" if _contact else _BASE_UA


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": user_agent(),
            "Accept-Language": "en-US,en;q=0.8",
        })
    return _session


def _throttle(domain: str) -> None:
    with _lock:
        wait = _last_hit.get(domain, 0) + _delay_seconds - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_hit[domain] = time.monotonic()


def robots_allowed(url: str) -> bool:
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    if root not in _robots:
        rp = RobotFileParser()
        try:
            _throttle(parsed.netloc)
            r = session().get(root + "/robots.txt", timeout=TIMEOUT)
            if r.status_code in (401, 403):
                rp.disallow_all = True
            elif r.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException:
            # robots.txt unreachable: be conservative only for this run
            rp.disallow_all = True
        _robots[root] = rp
    rp = _robots[root]
    return rp.can_fetch(user_agent(), url) if rp else True


def _cache_key(url: str, params: dict | None) -> str:
    raw = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items())
                                if k.lower() != "key")
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str):
    from .db import session_scope
    from .models import HttpCache
    with session_scope() as s:
        row = s.get(HttpCache, key)
        if row and row.expires_at > clock.utcnow():
            return Response(url=row.url, status=row.status, text=row.body, from_cache=True)
    return None


def _cache_put(key: str, resp: Response, ttl: timedelta) -> None:
    from .db import session_scope
    from .models import HttpCache
    now = clock.utcnow()
    with session_scope() as s:
        row = s.get(HttpCache, key)
        if row is None:
            row = HttpCache(key=key)
            s.add(row)
        row.url, row.status, row.body = resp.url, resp.status, resp.text
        row.fetched_at, row.expires_at = now, now + ttl


def purge_cache() -> int:
    from sqlalchemy import delete
    from .db import session_scope
    from .models import HttpCache
    with session_scope() as s:
        res = s.execute(delete(HttpCache).where(HttpCache.expires_at < clock.utcnow()))
        return res.rowcount or 0


def get(url: str, *, params: dict | None = None, ttl: timedelta = timedelta(hours=6),
        check_robots: bool = True, use_cache: bool = True, headers: dict | None = None,
        detect_restrictions: bool = True) -> Response:
    """GET with caching. Raises AccessRestricted or requests.RequestException."""
    key = _cache_key(url, params)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    if check_robots and not robots_allowed(url):
        raise AccessRestricted(f"robots.txt disallows {url}")
    _throttle(urlparse(url).netloc)
    r = session().get(url, params=params, timeout=TIMEOUT, headers=headers or {})
    if r.status_code in (401, 402, 403, 407, 429):
        raise AccessRestricted(f"HTTP {r.status_code} from {urlparse(r.url).netloc}")
    text = r.text if r.encoding or "text" in r.headers.get("Content-Type", "") \
        or "xml" in r.headers.get("Content-Type", "") or "json" in r.headers.get("Content-Type", "") \
        else r.content.decode("utf-8", "replace")
    if detect_restrictions and r.status_code == 200 and looks_blocked(text):
        raise AccessRestricted(f"Page at {urlparse(r.url).netloc} shows a CAPTCHA/paywall/login wall")
    resp = Response(url=r.url, status=r.status_code, text=text)
    if use_cache and r.status_code < 400:
        _cache_put(key, resp, ttl)
    return resp


def get_json(url: str, *, params: dict | None = None, ttl: timedelta = timedelta(hours=12),
             use_cache: bool = True, headers: dict | None = None) -> dict:
    """GET an official JSON API (no robots check: APIs are meant for programmatic use)."""
    import json
    key = _cache_key(url, params)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return json.loads(cached.text)
    _throttle(urlparse(url).netloc)
    r = session().get(url, params=params, timeout=TIMEOUT, headers=headers or {})
    if r.status_code in (401, 403, 429):
        try:
            detail = r.json().get("error", {}).get("message", "")
        except ValueError:
            detail = r.text[:200]
        raise AccessRestricted(f"API returned HTTP {r.status_code}: {detail}")
    r.raise_for_status()
    data = r.json()
    if use_cache:
        _cache_put(key, Response(url=r.url, status=r.status_code, text=r.text), ttl)
    return data


def domain_of(url: str | None) -> str:
    if not url:
        return ""
    net = urlparse(url).netloc.lower()
    return net[4:] if net.startswith("www.") else net
