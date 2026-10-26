"""Test helpers: fake HTTP router (no network) and temp databases."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode

import requests

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, url: str, status: int = 200, text: str = "", content_type: str = "text/html; charset=utf-8"):
        self.url = url
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"
        self.headers = {"Content-Type": content_type}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for {self.url}")


class FakeSession:
    """Routes requests by URL prefix to fixture content. Unknown URLs raise ConnectionError."""

    def __init__(self, routes: dict[str, tuple[int, str, str] | callable]):
        self.routes = routes
        self.calls: list[str] = []
        self.headers: dict = {}

    def get(self, url, params=None, timeout=None, headers=None):
        full = url + ("?" + urlencode(params) if params else "")
        self.calls.append(full)
        if url.endswith("/robots.txt"):
            return FakeResponse(url, 404, "")
        for prefix in sorted(self.routes, key=len, reverse=True):
            if url.startswith(prefix):
                route = self.routes[prefix]
                if callable(route):
                    return route(url, params or {})
                status, body, ctype = route
                return FakeResponse(url, status, body, ctype)
        raise requests.ConnectionError(f"no route for {url}")


def default_routes() -> dict:
    return {
        "https://news.google.com/rss/search": (200, fixture("google_news.xml"), "application/xml"),
        "https://www.bing.com/news/search": (200, fixture("bing_news.xml"), "application/rss+xml"),
        "https://news.example.com/2026/10/22/tractor-chase": (200, fixture("article_tractor.html"), "text/html"),
        "https://mockingbirdsheriff.gov/divisions/records": (200, fixture("agency_records.html"), "text/html"),
        "https://mockingbirdsheriff.gov/": (200, fixture("agency_home.html"), "text/html"),
        "https://www.googleapis.com/youtube/v3/search": (200, fixture("yt_search.json"), "application/json"),
        "https://www.googleapis.com/youtube/v3/videos": (200, fixture("yt_videos.json"), "application/json"),
        "https://www.googleapis.com/youtube/v3/channels": (200, fixture("yt_channels.json"), "application/json"),
        "https://www.googleapis.com/youtube/v3/playlistItems": (200, fixture("yt_playlist.json"), "application/json"),
        "https://feeds.example.gov/news.rss": (200, fixture("bing_news.xml"), "application/rss+xml"),
    }


def install_fake_network(routes: dict | None = None) -> FakeSession:
    from bch import net
    fake = FakeSession(routes or default_routes())
    net._session = fake
    net._robots.clear()
    net._last_hit.clear()
    net._delay_seconds = 0.0
    return fake


def no_sleep_throttle():
    from bch import net
    net._throttle = lambda domain: None  # tests should not wait between requests


def temp_db() -> Path:
    from bch import db
    d = Path(tempfile.mkdtemp(prefix="bch_test_"))
    path = d / "test.sqlite3"
    os.environ["BCH_DB_PATH"] = str(path)
    db.init_db(path)
    return path
