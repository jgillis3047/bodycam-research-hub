"""Incident discovery collectors: Google News RSS, Bing News RSS and user-configured feeds
(police/sheriff newsrooms, local outlets). Also optional article-page enrichment.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from . import analysis, feeds, net

log = logging.getLogger(__name__)


@dataclass
class RawItem:
    title: str
    url: str
    source_name: str
    source_domain: str
    published: datetime | None
    summary: str
    collector: str
    query: str = ""
    state_hint: str | None = None
    is_official: bool = False
    text_excerpt: str = ""
    fetched_full_text: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(x for x in (self.title, self.summary, self.text_excerpt) if x)


@dataclass
class SearchTask:
    query: str
    state: str
    category: str | None
    location: str | None = None


def build_search_plan(states: list[str], categories: list[str], extra_locations: list[dict]) -> list[SearchTask]:
    tasks: list[SearchTask] = []
    for st in states:
        for cat in categories:
            meta = analysis.CATEGORIES.get(cat)
            if meta:
                tasks.append(SearchTask(f'"{st}" {meta["query"]}', st, cat))
    for loc in extra_locations or []:
        st = loc.get("state") or ""
        place = loc.get("city") or loc.get("county") or ""
        if not place:
            continue
        tasks.append(SearchTask(
            f'"{place}" {st} (police OR deputies OR troopers) (chase OR arrested OR bodycam OR standoff OR DUI)',
            st, None, place))
        if loc.get("agency"):
            tasks.append(SearchTask(f'"{loc["agency"]}"', st, None, place))
    return tasks


def _clean_summary(summary_html: str, title: str) -> str:
    text = feeds.strip_html(summary_html)
    # Google News summaries just repeat the headline + outlet name
    if not text or text.lower().startswith(title.lower()[:40]):
        return ""
    return text[:1500]


def fetch_google_news(task: SearchTask, days: int) -> list[RawItem]:
    resp = net.get(feeds.GOOGLE_NEWS_RSS, params=feeds.google_news_params(task.query, days),
                   ttl=timedelta(hours=3), check_robots=False, detect_restrictions=False)
    out = []
    for it in feeds.parse_feed(resp.text):
        headline, outlet = feeds.split_google_title(it.title, it.source_name)
        out.append(RawItem(
            title=headline, url=it.link, source_name=outlet or it.source_name,
            source_domain=net.domain_of(it.source_url) or "", published=it.published,
            summary=_clean_summary(it.summary, headline), collector="google_news",
            query=task.query, state_hint=task.state))
    return out


def fetch_bing_news(task: SearchTask, days: int) -> list[RawItem]:
    resp = net.get(feeds.BING_NEWS_RSS, params=feeds.bing_news_params(task.query),
                   ttl=timedelta(hours=3), check_robots=False, detect_restrictions=False)
    out = []
    for it in feeds.parse_feed(resp.text):
        url = feeds.resolve_bing_link(it.link)
        out.append(RawItem(
            title=it.title, url=url, source_name=it.source_name or net.domain_of(url),
            source_domain=net.domain_of(url), published=it.published,
            summary=_clean_summary(it.summary, it.title), collector="bing_news",
            query=task.query, state_hint=task.state))
    return out


def fetch_configured_feed(url: str, name: str, state: str | None, is_official: bool) -> list[RawItem]:
    resp = net.get(url, ttl=timedelta(hours=2), check_robots=True, detect_restrictions=False)
    out = []
    for it in feeds.parse_feed(resp.text):
        link = it.link or url
        out.append(RawItem(
            title=it.title, url=link, source_name=name, source_domain=net.domain_of(link),
            published=it.published, summary=feeds.strip_html(it.summary)[:3000],
            collector=f"feed:{name}", state_hint=state, is_official=is_official))
    return out


# ---------------------------------------------------------------------------
# Article enrichment
# ---------------------------------------------------------------------------
def can_enrich(item: RawItem) -> bool:
    d = net.domain_of(item.url)
    return bool(item.url.startswith("http") and d and "news.google.com" not in d and "bing.com" not in d)


def extract_article(html_text: str) -> dict:
    soup = BeautifulSoup(html_text, "html.parser")
    meta = {}
    for tag in soup.find_all("meta"):
        k = (tag.get("property") or tag.get("name") or "").lower()
        if k in ("og:description", "description", "article:published_time", "og:title",
                 "parsely-pub-date", "date", "dc.date", "pubdate"):
            meta.setdefault(k, tag.get("content") or "")
    published = None
    for k in ("article:published_time", "parsely-pub-date", "pubdate", "dc.date", "date"):
        if meta.get(k):
            published = feeds._parse_date(meta[k])
            if published:
                break
    if published is None:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            for obj in data if isinstance(data, list) else [data]:
                if isinstance(obj, dict) and obj.get("datePublished"):
                    published = feeds._parse_date(obj["datePublished"])
                    break
            if published:
                break
    for t in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        t.decompose()
    container = soup.find("article") or soup.find("main") or soup
    paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    paras = [p for p in paras if len(p) > 60 and not re.search(r"(cookie|subscribe|newsletter|all rights reserved|sign up)", p, re.I)]
    body = re.sub(r"\s+", " ", " ".join(paras))[:2500]
    return {"description": meta.get("og:description") or meta.get("description") or "",
            "published": published, "text": body}


def enrich(item: RawItem) -> RawItem:
    """Fetch the publisher page (robots.txt respected) for more incident detail."""
    if not can_enrich(item):
        return item
    try:
        resp = net.get(item.url, ttl=timedelta(days=3))
    except net.AccessRestricted as exc:
        item.extra["enrich_error"] = str(exc)
        return item
    except Exception as exc:  # noqa: BLE001 - network problems are not fatal
        item.extra["enrich_error"] = str(exc)
        return item
    art = extract_article(resp.text)
    if art["description"] and not item.summary:
        item.summary = art["description"][:1500]
    if art["text"]:
        item.text_excerpt = art["text"]
        item.fetched_full_text = True
    if not item.published and art["published"]:
        item.published = art["published"]
    return item
