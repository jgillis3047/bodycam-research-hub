"""Records-custodian research: find the agency's official website, its public-records page, request
portal, records e-mail and published fee information.

Trust model (see models.Verification):
* "Found on official .gov site": the item was extracted from a page on a .gov domain whose page text
  names the agency/jurisdiction. Shown as a clickable portal link.
* "Unverified candidate": found on a non-.gov site, or matched by heuristics only. NOT shown as the
  portal link until you confirm it with "Mark verified".
* "Verified by you": you confirmed it (or typed it in yourself).
Nothing is ever constructed or guessed into the database without having been fetched successfully.
"""
from __future__ import annotations

from . import clock
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import analysis, config, net
from .models import Agency, Verification

PORTAL_PLATFORMS = {
    "nextrequest.com": "NextRequest",
    "govqa.us": "GovQA",
    "mycusthelp.com": "GovQA",
    "mycusthelp.net": "GovQA",
    "justfoia.com": "JustFOIA",
    "foiaxpress": "FOIAXpress",
    "civicplus.help": "CivicPlus",
    "crimewatchpa.com": "CrimeWatch",
    "crimewatch.net": "CrimeWatch",
    "smartsheet.com": "Smartsheet form",
    "seamlessdocs.com": "SeamlessDocs",
    "govbuilt.com": "GovBuilt",
    "laserfiche": "Laserfiche Forms",
    "jotform.com": "Jotform",
    "public-records-request": "Online form",
}
RECORDS_LINK_RE = re.compile(
    r"(public[\s-]*records?|records?[\s-]*requests?|open[\s-]*records?|right[\s-]*to[\s-]*know|"
    r"\bfoia\b|\bfoi\b|freedom of information|sunshine|records division|records section|"
    r"public information request|\bpia\b|body[\s-]*(?:worn|cam)|bwc|video request|act 22|cpra|"
    r"report request|request (?:a )?report|records unit)", re.I)
REQUEST_LINK_RE = re.compile(r"(submit|request|portal|online|form|make a)", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RECORDS_EMAIL_HINT = re.compile(r"(record|foia|prr|pra|cpra|rtk|righttoknow|publicinfo|openrec|sunshine|pio|custodian|bwc|video)", re.I)
FEE_RE = re.compile(r"[^.\n]{0,160}(?:\$\s?\d[\d,]*(?:\.\d{2})?)[^.\n]{0,160}", re.I)
FEE_CONTEXT = re.compile(r"(fee|cost|charge|per (?:hour|page|minute|disc|dvd|cd|video|recording|copy)|deposit|labor|redact)", re.I)
PHONE_RE = re.compile(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")

MAX_PAGES = 12


@dataclass
class ResearchResult:
    website: str | None = None
    website_status: str = Verification.NOT_FOUND
    records_page_url: str | None = None
    portal_url: str | None = None
    portal_platform: str | None = None
    portal_status: str = Verification.NOT_FOUND
    records_email: str | None = None
    email_status: str = Verification.NOT_FOUND
    records_phone: str | None = None
    fee_info: str | None = None
    fee_source_url: str | None = None
    request_instructions: str | None = None
    evidence: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    log: list = field(default_factory=list)


def is_gov(url: str | None) -> bool:
    d = net.domain_of(url)
    return d.endswith(".gov") or d.endswith(".mil")


def _platform_for(url: str) -> str | None:
    low = url.lower()
    for key, name in PORTAL_PLATFORMS.items():
        if key in low:
            return name
    return None


def _jurisdiction_words(agency: Agency) -> list[str]:
    words = []
    if agency.city:
        words.append(agency.city.lower())
    if agency.county:
        words.append(agency.county.lower().replace(" county", ""))
    core = re.sub(r"(police department|sheriff's office|sheriff's department|police|sheriff|"
                  r"department of public safety|highway patrol|state patrol|state police)$", "",
                  analysis.normalize_agency(agency.name)).strip()
    core = re.sub(r"^city of ", "", core).replace(" county", "").strip()
    if core:
        words.append(core)
    return [w for w in dict.fromkeys(words) if w]


def page_mentions_agency(html_text: str, agency: Agency) -> bool:
    soup = BeautifulSoup(html_text, "html.parser")
    title = (soup.title.get_text(" ") if soup.title else "").lower()
    body = soup.get_text(" ")[:30000].lower().replace("’", "'")
    words = _jurisdiction_words(agency)
    if not words:
        return False
    hits = sum(1 for w in words if w in title or w in body)
    return hits >= 1 and (any(w in title for w in words) or any(t in body for t in ("police", "sheriff", "patrol")))


# ---------------------------------------------------------------------------
# Website discovery
# ---------------------------------------------------------------------------
# Hostnames to TRY for state-level agencies. Like every candidate, they are only kept if the page loads
# and names the agency; nothing here is shown to the user unless that check passes.
STATE_AGENCY_HOSTS = {
    "florida highway patrol": ["www.flhsmv.gov"],
    "ohio state highway patrol": ["statepatrol.ohio.gov"],
    "wisconsin state patrol": ["wisconsindot.gov"],
    "texas department of public safety": ["www.dps.texas.gov"],
    "pennsylvania state police": ["www.psp.pa.gov"],
    "california highway patrol": ["www.chp.ca.gov"],
}


def candidate_gov_domains(agency: Agency) -> list[str]:
    """Plausible .gov hostnames to TRY. A candidate is only kept if it loads and names the agency."""
    st = (analysis.US_STATES.get(agency.state or "", "") or "").lower()
    out: list[str] = list(STATE_AGENCY_HOSTS.get(analysis.normalize_agency(agency.name), []))
    slug = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    kind = analysis.classify_agency(agency.name)
    if kind == "sheriff" and agency.county:
        c = slug(agency.county.replace(" County", ""))
        out += [f"{c}sheriff.gov", f"{c}so.gov", f"{c}countysheriff.gov", f"{c}county{st}.gov",
                f"{c}county.gov", f"co.{c}.{st}.us"]
    city = agency.city
    if not city and kind == "police":
        m = re.match(r"(?:City of )?(.+?) Police", agency.name)
        city = m.group(1) if m else None
    if city:
        c = slug(city)
        out += [f"{c}{st}.gov", f"{c}.gov", f"cityof{c}.gov", f"{c}police.gov", f"{c}pd.gov",
                f"cityof{c}{st}.gov", f"ci.{c}.{st}.us"]
    return list(dict.fromkeys(out))


def brave_search(query: str, count: int = 8) -> list[dict]:
    key = config.get_env("BRAVE_SEARCH_API_KEY")
    if not key:
        return []
    data = net.get_json("https://api.search.brave.com/res/v1/web/search",
                        params={"q": query, "count": count, "country": "us"},
                        headers={"X-Subscription-Token": key, "Accept": "application/json"},
                        ttl=timedelta(days=14))
    return [{"url": r.get("url"), "title": r.get("title", ""), "description": r.get("description", "")}
            for r in data.get("web", {}).get("results", []) if r.get("url")]


def find_website(agency: Agency, result: ResearchResult) -> str | None:
    if agency.website and agency.website_status == Verification.USER_VERIFIED:
        result.website, result.website_status = agency.website, Verification.USER_VERIFIED
        return agency.website

    # 1) Optional search API
    try:
        hits = brave_search(f'"{agency.name}" {agency.state or ""} official site')
    except (net.AccessRestricted, Exception) as exc:  # noqa: BLE001 - optional integration
        hits = []
        result.log.append(f"Brave search failed: {exc}")
    for h in hits:
        url = h["url"]
        if is_gov(url):
            root = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
            result.log.append(f"Search result on .gov domain: {root}")
            if _confirm_site(root, agency, result):
                return root
    for h in hits[:3]:
        if not is_gov(h["url"]):
            result.candidates.append({"field": "website", "url": h["url"],
                                      "note": f"Search result (not .gov): {h['title'][:80]}"})

    # 2) Try plausible .gov hostnames (kept only if the page loads and names the jurisdiction)
    for host in candidate_gov_domains(agency):
        url = f"https://{host}/"
        if _confirm_site(url, agency, result, quiet=True):
            return result.website
    result.log.append("No official .gov website confirmed automatically. Add it on the Agencies page.")
    return None


def _confirm_site(url: str, agency: Agency, result: ResearchResult, quiet: bool = False) -> bool:
    try:
        resp = net.get(url, ttl=timedelta(days=14))
    except (net.AccessRestricted, Exception) as exc:  # noqa: BLE001 - network errors are expected here
        if not quiet:
            result.log.append(f"Could not load {url}: {exc}")
        return False
    if resp.status >= 400:
        return False
    if page_mentions_agency(resp.text, agency):
        final = resp.url or url
        result.website = f"{urlparse(final).scheme}://{urlparse(final).netloc}/"
        result.website_status = Verification.OFFICIAL_SITE if is_gov(final) else Verification.UNVERIFIED
        result.evidence.append({"field": "website", "url": final,
                                "snippet": "Page loaded and names the jurisdiction/agency"})
        result.log.append(f"Website confirmed: {final}")
        return True
    if not quiet:
        result.log.append(f"{url} loaded but did not name the agency; skipped")
    return False


# ---------------------------------------------------------------------------
# Crawl for records information
# ---------------------------------------------------------------------------
def extract_records_info(html_text: str, page_url: str) -> dict:
    """Pure function: pull records-related links, e-mails, phones and fee text out of one page."""
    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    links, portals, emails = [], [], []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True)
        full = urljoin(page_url, href)
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if EMAIL_RE.fullmatch(addr):
                emails.append({"email": addr, "label": text})
            continue
        if not full.startswith("http"):
            continue
        plat = _platform_for(full)
        if plat:
            portals.append({"url": full, "platform": plat, "text": text})
        elif RECORDS_LINK_RE.search(text) or RECORDS_LINK_RE.search(href):
            links.append({"url": full, "text": text,
                          "looks_like_request": bool(REQUEST_LINK_RE.search(text + " " + href))})
    body_text = soup.get_text(" ")
    body_text = re.sub(r"\s+", " ", body_text)
    for addr in EMAIL_RE.findall(body_text):
        if addr not in [e["email"] for e in emails]:
            emails.append({"email": addr, "label": ""})
    fees = []
    for m in FEE_RE.finditer(body_text):
        snippet = m.group(0).strip()
        if FEE_CONTEXT.search(snippet):
            fees.append(snippet[:300])
    bodycam = [s.strip() for s in re.findall(r"[^.]{0,200}(?:body[\s-]*(?:worn|cam)\w*|bwc|video record\w*)[^.]{0,200}\.",
                                             body_text, re.I)][:5]
    phones = []
    for m in PHONE_RE.finditer(body_text):
        ctx = body_text[max(0, m.start() - 60): m.start()].lower()
        if "record" in ctx:
            phones.append(m.group(0))
    is_records_page = bool(RECORDS_LINK_RE.search((soup.title.get_text() if soup.title else "") + " "
                                                  + " ".join(h.get_text(" ") for h in soup.find_all(["h1", "h2"]))))
    return {"links": links, "portals": portals, "emails": emails, "fees": fees[:6],
            "bodycam_text": bodycam, "phones": phones[:3], "is_records_page": is_records_page}


def crawl_records(start_url: str, agency: Agency, result: ResearchResult) -> None:
    site_is_gov = is_gov(start_url)
    trust = Verification.OFFICIAL_SITE if site_is_gov else Verification.UNVERIFIED
    site_domain = net.domain_of(start_url)
    queue = [start_url]
    seen: set[str] = set()
    pages = 0
    best_records_page = None
    while queue and pages < MAX_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = net.get(url, ttl=timedelta(days=7))
        except net.AccessRestricted as exc:
            result.log.append(f"Skipped (access restricted): {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            result.log.append(f"Failed to load {url}: {exc}")
            continue
        pages += 1
        info = extract_records_info(resp.text, resp.url or url)
        if info["is_records_page"] and not best_records_page and url != start_url:
            best_records_page = resp.url or url

        for p in info["portals"]:
            if not result.portal_url:
                result.portal_url, result.portal_platform = p["url"], p["platform"]
                result.portal_status = trust
                result.evidence.append({"field": "portal", "url": resp.url or url,
                                        "snippet": f"Link '{p['text'][:80]}' -> {p['url']}"})
                result.log.append(f"Portal link ({p['platform']}) found on {url}")
        for ln in info["links"]:
            same_site = net.domain_of(ln["url"]).endswith(site_domain) or site_domain.endswith(net.domain_of(ln["url"]))
            if same_site and ln["url"] not in seen and len(queue) < 30:
                # visit records-ish pages first
                queue.insert(0, ln["url"]) if ln["looks_like_request"] else queue.append(ln["url"])
            if ln["looks_like_request"] and not result.portal_url and info["is_records_page"]:
                status = trust if same_site else Verification.UNVERIFIED
                result.candidates.append({"field": "portal", "url": ln["url"],
                                          "note": f"Request link '{ln['text'][:60]}' on {url}",
                                          "status": status})
        for e in info["emails"]:
            if RECORDS_EMAIL_HINT.search(e["email"]) or (info["is_records_page"] and RECORDS_EMAIL_HINT.search(e["label"] or "")):
                if not result.records_email:
                    email_gov = e["email"].lower().endswith(".gov")
                    result.records_email = e["email"]
                    result.email_status = trust if (site_is_gov or email_gov) else Verification.UNVERIFIED
                    result.evidence.append({"field": "email", "url": resp.url or url,
                                            "snippet": f"{e['email']} {e['label'][:60]}".strip()})
            elif info["is_records_page"]:
                result.candidates.append({"field": "email", "url": resp.url or url, "value": e["email"],
                                          "note": "E-mail on records page (not obviously the records address)"})
        if info["fees"] and info["is_records_page"] and not result.fee_info:
            result.fee_info = " | ".join(info["fees"][:3])
            result.fee_source_url = resp.url or url
            result.evidence.append({"field": "fees", "url": resp.url or url, "snippet": result.fee_info[:300]})
        if info["bodycam_text"] and info["is_records_page"]:
            result.evidence.append({"field": "bodycam_policy", "url": resp.url or url,
                                    "snippet": " ".join(info["bodycam_text"][:2])[:400]})
        if info["phones"] and not result.records_phone:
            result.records_phone = info["phones"][0]

    if best_records_page:
        result.records_page_url = best_records_page
    # Promote a same-site request link on a .gov records page when no third-party portal exists
    if not result.portal_url:
        for c in result.candidates:
            if c["field"] == "portal" and c.get("status") == Verification.OFFICIAL_SITE:
                result.portal_url, result.portal_platform = c["url"], "Agency web form/page"
                result.portal_status = Verification.OFFICIAL_SITE
                result.evidence.append({"field": "portal", "url": c["url"], "snippet": c["note"]})
                break
    result.log.append(f"Crawled {pages} page(s) on {site_domain}")


def build_instructions(agency: Agency, res: ResearchResult) -> str:
    from .state_laws import law_for
    law = law_for(agency.state)
    lines = []
    if res.portal_url and res.portal_status in Verification.TRUSTED:
        lines.append(f"1. Submit online through the agency's records portal ({res.portal_platform or 'web form'}).")
    elif res.records_email and res.email_status in Verification.TRUSTED:
        lines.append(f"1. E-mail the request to {res.records_email}.")
    elif res.records_page_url:
        lines.append("1. Follow the submission instructions on the agency's public records page.")
    else:
        lines.append("1. Confirm the records custodian: call the agency's non-emergency line and ask for the records unit.")
    lines.append("2. Ask specifically for body-worn camera AND in-car/dash camera video (plus 911 audio if relevant).")
    lines.append("3. Include date, approximate time, location, and any report/case number you have.")
    for req in law.get("special_requirements", []):
        lines.append(f"   - {agency.state}: {req}")
    lines.append("4. Ask for a fee estimate before any work begins; state your spending limit.")
    lines.append("5. Log the submission in the Request Tracker and set a follow-up date.")
    return "\n".join(lines)


def research_agency(agency: Agency) -> ResearchResult:
    res = ResearchResult()
    site = find_website(agency, res)
    if site:
        crawl_records(site, agency, res)
    # Never downgrade information you verified yourself
    if agency.portal_status == Verification.USER_VERIFIED:
        res.portal_url, res.portal_status = agency.portal_url, agency.portal_status
        res.portal_platform = agency.portal_platform
    if agency.email_status == Verification.USER_VERIFIED:
        res.records_email, res.email_status = agency.records_email, agency.email_status
    res.request_instructions = build_instructions(agency, res)
    return res


def apply_result(agency: Agency, res: ResearchResult) -> None:
    keep_site = agency.website_status == Verification.USER_VERIFIED
    if not keep_site:
        agency.website, agency.website_status = res.website, res.website_status
    if res.records_page_url:
        agency.records_page_url = res.records_page_url
    agency.portal_url, agency.portal_status = res.portal_url, res.portal_status
    agency.portal_platform = res.portal_platform
    agency.records_email, agency.email_status = res.records_email, res.email_status
    if res.records_phone:
        agency.records_phone = res.records_phone
    if res.fee_info:
        agency.fee_info, agency.fee_source_url = res.fee_info, res.fee_source_url
    agency.request_instructions = res.request_instructions
    agency.evidence = res.evidence
    agency.candidates = res.candidates
    agency.research_log = "\n".join(res.log)
    agency.last_researched_at = clock.utcnow()


def trusted_portal(agency: Agency | None) -> str | None:
    if agency and agency.portal_url and agency.portal_status in Verification.TRUSTED:
        return agency.portal_url
    return None


def trusted_email(agency: Agency | None) -> str | None:
    if agency and agency.records_email and agency.email_status in Verification.TRUSTED:
        return agency.records_email
    return None
