"""RSS/Atom feed parsing plus Google News / Bing News RSS query builders."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

try:
    import feedparser  # type: ignore
except ImportError:  # pragma: no cover
    feedparser = None


@dataclass
class FeedItem:
    title: str
    link: str
    published: datetime | None
    summary: str = ""
    source_name: str = ""
    source_url: str = ""
    extra: dict = field(default_factory=dict)


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _to_utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _to_utc_naive(parsedate_to_datetime(value))
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return _to_utc_naive(dateparser.parse(value))
    except (ValueError, OverflowError, TypeError):
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.split(":")[-1].lower()


def _parse_with_etree(xml_text: str) -> list[FeedItem]:
    # Namespaced prefixes such as <News:Source> without declarations break ElementTree; strip them.
    cleaned = re.sub(r"<(/?)([A-Za-z]+):([A-Za-z]+)", r"<\1\2_\3", xml_text)
    cleaned = re.sub(r"\sxmlns(:\w+)?=\"[^\"]*\"", "", cleaned)
    root = ET.fromstring(cleaned.encode("utf-8"))
    items: list[FeedItem] = []
    nodes = [n for n in root.iter() if _local(n.tag) in ("item", "entry")]
    for node in nodes:
        data: dict[str, str] = {}
        src_url = ""
        link = ""
        for child in node:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "link":
                link = child.get("href") or text or link
            elif name in ("source", "news_source"):
                data["source"] = text
                src_url = child.get("url", "") or src_url
            else:
                data.setdefault(name, text)
        items.append(FeedItem(
            title=strip_html(data.get("title")),
            link=link,
            published=_parse_date(data.get("pubdate") or data.get("published") or data.get("updated")
                                  or data.get("dc_date")),
            summary=data.get("description") or data.get("summary") or data.get("content") or "",
            source_name=data.get("source", ""),
            source_url=src_url,
        ))
    return items


def _parse_with_feedparser(xml_text: str) -> list[FeedItem]:
    parsed = feedparser.parse(xml_text)
    items = []
    for e in parsed.entries:
        published = None
        for attr in ("published_parsed", "updated_parsed"):
            tup = e.get(attr)
            if tup:
                published = datetime(*tup[:6])
                break
        src = e.get("source")
        source_name = source_url = ""
        if isinstance(src, dict):
            source_name = src.get("title", "") or ""
            source_url = src.get("href", "") or src.get("url", "") or ""
        elif isinstance(src, str):
            source_name = src
        if not source_name and isinstance(e.get("news_source"), str):
            source_name = e.get("news_source")
        items.append(FeedItem(
            title=strip_html(e.get("title", "")),
            link=e.get("link", ""),
            published=published,
            summary=e.get("summary", "") or e.get("description", ""),
            source_name=source_name or "",
            source_url=source_url or "",
        ))
    return items


def parse_feed(xml_text: str) -> list[FeedItem]:
    """Parse RSS/Atom text into FeedItems. Uses feedparser when installed, else ElementTree."""
    items: list[FeedItem] = []
    if feedparser is not None:
        try:
            items = _parse_with_feedparser(xml_text)
        except Exception:  # pragma: no cover - fall back on any parser error
            items = []
    if not items:
        try:
            items = _parse_with_etree(xml_text)
        except ET.ParseError:
            return []
    # Bing-specific fields that feedparser does not expose reliably
    if "<News:Source>" in xml_text and any(not i.source_name for i in items):
        try:
            by_link = {i.link: i for i in _parse_with_etree(xml_text)}
            for i in items:
                if not i.source_name and i.link in by_link:
                    i.source_name = by_link[i.link].source_name
        except ET.ParseError:
            pass
    return items


# ---------------------------------------------------------------------------
# Google News & Bing News
# ---------------------------------------------------------------------------
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
BING_NEWS_RSS = "https://www.bing.com/news/search"


def google_news_params(query: str, days: int) -> dict:
    return {"q": f"{query} when:{int(days)}d", "hl": "en-US", "gl": "US", "ceid": "US:en"}


def google_news_url(query: str, days: int) -> str:
    p = google_news_params(query, days)
    return f"{GOOGLE_NEWS_RSS}?q={quote_plus(p['q'])}&hl=en-US&gl=US&ceid=US:en"


def bing_news_params(query: str) -> dict:
    return {"q": query, "format": "rss", "setlang": "en-US", "cc": "US"}


def split_google_title(title: str, source_name: str = "") -> tuple[str, str]:
    """Google News titles look like 'Headline - Outlet'. Returns (headline, outlet)."""
    if source_name and title.endswith(f" - {source_name}"):
        return title[: -len(source_name) - 3].strip(), source_name
    m = re.match(r"^(.*\S)\s+[-–—]\s+([^-–—]{2,60})$", title)
    if m:
        return m.group(1).strip(), (source_name or m.group(2).strip())
    return title.strip(), source_name


def resolve_bing_link(link: str) -> str:
    """Bing RSS links wrap the publisher URL in apiclick.aspx?url=...; return the publisher URL."""
    try:
        parsed = urlparse(link)
        if "bing.com" in parsed.netloc:
            q = parse_qs(parsed.query)
            if q.get("url"):
                return q["url"][0]
    except ValueError:
        pass
    return link


def find_feed_links(html_text: str, base_url: str) -> list[str]:
    """Find <link rel=alternate type=rss/atom> feed URLs on a page."""
    from urllib.parse import urljoin
    soup = BeautifulSoup(html_text, "html.parser")
    out = []
    for tag in soup.find_all("link", attrs={"rel": True}):
        rel = " ".join(tag.get("rel")).lower() if isinstance(tag.get("rel"), list) else str(tag.get("rel")).lower()
        typ = (tag.get("type") or "").lower()
        if "alternate" in rel and ("rss" in typ or "atom" in typ) and tag.get("href"):
            out.append(urljoin(base_url, tag["href"]))
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"(rss|\.xml$|/feed/?$|atom)", href, re.I) and len(out) < 20:
            out.append(urljoin(base_url, href))
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq
