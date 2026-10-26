"""Rule-based incident analysis: relevance, categories, agency/location/date extraction, footage
signals, risk flags, and duplicate clustering.

Everything here works from text that actually appeared in a source. Each extracted value comes with a
"basis" string that says HOW it was obtained, so the UI can separate stated facts from inferences.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------
US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}
AP_ABBREVIATIONS = {
    "Ala.": "Alabama", "Ariz.": "Arizona", "Ark.": "Arkansas", "Calif.": "California",
    "Colo.": "Colorado", "Conn.": "Connecticut", "Del.": "Delaware", "Fla.": "Florida",
    "Ga.": "Georgia", "Ill.": "Illinois", "Ind.": "Indiana", "Kan.": "Kansas", "Ky.": "Kentucky",
    "La.": "Louisiana", "Md.": "Maryland", "Mass.": "Massachusetts", "Mich.": "Michigan",
    "Minn.": "Minnesota", "Miss.": "Mississippi", "Mo.": "Missouri", "Mont.": "Montana",
    "Neb.": "Nebraska", "Nev.": "Nevada", "N.H.": "New Hampshire", "N.J.": "New Jersey",
    "N.M.": "New Mexico", "N.Y.": "New York", "N.C.": "North Carolina", "N.D.": "North Dakota",
    "Okla.": "Oklahoma", "Ore.": "Oregon", "Pa.": "Pennsylvania", "R.I.": "Rhode Island",
    "S.C.": "South Carolina", "S.D.": "South Dakota", "Tenn.": "Tennessee", "Tex.": "Texas",
    "Vt.": "Vermont", "Va.": "Virginia", "Wash.": "Washington", "W.Va.": "West Virginia",
    "Wis.": "Wisconsin", "Wyo.": "Wyoming",
}
# Rough UTC offsets (standard time) used only to convert article publish times to a local day.
STATE_UTC_OFFSET = {"California": -8, "Washington": -7, "Oregon": -8, "Nevada": -8, "Arizona": -7,
                    "Texas": -6, "Wisconsin": -6, "Illinois": -6, "Minnesota": -6, "Louisiana": -6,
                    "Florida": -5, "Ohio": -5, "Pennsylvania": -5, "New York": -5, "Georgia": -5}

STATE_AGENCIES = {
    "Florida": [("Florida Highway Patrol", ["Florida Highway Patrol", "FHP"])],
    "Ohio": [("Ohio State Highway Patrol", ["Ohio State Highway Patrol", "OSHP", "Ohio State Patrol"])],
    "Wisconsin": [("Wisconsin State Patrol", ["Wisconsin State Patrol"])],
    "Texas": [("Texas Department of Public Safety",
               ["Texas Department of Public Safety", "Texas DPS", "DPS troopers", "DPS trooper"])],
    "Pennsylvania": [("Pennsylvania State Police", ["Pennsylvania State Police", "PSP troopers"])],
    "California": [("California Highway Patrol", ["California Highway Patrol", "CHP"])],
}

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
CATEGORIES: dict[str, dict] = {
    "pursuit": {
        "label": "Police pursuit / chase",
        "pattern": r"\b(chase[sd]?|pursuit|high[- ]speed|pit maneuver|fled (?:from )?(?:police|deputies|troopers|officers)|stop sticks|tire deflation)\b",
        "query": '(chase OR pursuit OR "high-speed") (police OR deputies OR troopers)',
        "base_interest": 8,
    },
    "dui": {
        "label": "DUI / impaired driving",
        "pattern": r"\b(dui|dwi|ovi|owi|drunk(?:en)? driv\w*|impaired driv\w*|intoxicated|blood alcohol|bac of|sobriety test)\b",
        "query": '(DUI OR DWI OR OVI OR OWI OR "drunk driver") arrested',
        "base_interest": 5,
    },
    "standoff": {
        "label": "Standoff / barricade",
        "pattern": r"\b(standoff|barricaded|swat|hostage|holed up)\b",
        "query": '(standoff OR barricaded OR SWAT) (police OR deputies)',
        "base_interest": 7,
    },
    "robbery": {
        "label": "Robbery / carjacking",
        "pattern": r"\b(robbery|robbed|robbing|carjack\w*|hold[- ]?up|armed robbery|stickup)\b",
        "query": '(robbery OR carjacking OR "armed robbery") arrested police',
        "base_interest": 5,
    },
    "fleeing": {
        "label": "Suspect fleeing",
        "pattern": r"\b(fled on foot|foot (?:chase|pursuit)|ran from (?:police|deputies|officers)|escaped (?:custody|from)|took off running|tried to flee|attempted to flee)\b",
        "query": '("fled on foot" OR "foot chase" OR "ran from" OR "escaped custody") (police OR deputies)',
        "base_interest": 7,
    },
    "disorderly": {
        "label": "Disorderly / resisting",
        "pattern": r"\b(disorderly|resisting (?:arrest|an officer|without violence|with violence)|brawl|unruly|battery on (?:a |an )?(?:officer|deputy|law enforcement)|spit on|kicked (?:an? )?(?:officer|deputy))\b",
        "query": '("disorderly conduct" OR "resisting arrest" OR brawl OR unruly) arrested',
        "base_interest": 6,
    },
    "traffic_stop": {
        "label": "Unusual traffic stop",
        "pattern": r"\b(traffic stop|pulled over|routine stop|stopped for speeding)\b",
        "query": '"traffic stop" (arrested OR found OR bodycam OR deputies)',
        "base_interest": 5,
    },
    "rescue": {
        "label": "Police rescue",
        "pattern": r"\b(rescued?|rescuing|saved|narcan|pulled (?:a |the )?\w+ from|burning (?:car|vehicle|home)|life[- ]saving)\b",
        "query": '(rescued OR rescue OR "saved") (officer OR deputy OR trooper)',
        "base_interest": 6,
    },
    "bizarre": {
        "label": "Bizarre / unusual behavior",
        "pattern": r"\b(bizarre|naked|nude|strange|wrong[- ]way|alligator|gator|florida man|weird|unusual|claimed to be|told (?:deputies|officers|police) (?:he|she|they) (?:was|were)|stole an? (?:\w+ )?(?:bus|tractor|police car|patrol car|cruiser|golf cart|forklift|boat|ambulance|fire truck|bulldozer|excavator)|on a (?:riding )?lawn ?mower|(?:drove|driving|crashed) (?:\w+ ){0,2}into (?:a |the )(?:pond|lake|canal|pool|river|store|house|restaurant))\b",
        "query": '(bizarre OR naked OR "wrong-way" OR strange OR alligator) arrested (police OR deputies)',
        "base_interest": 9,
    },
    "confrontation": {
        "label": "Police confrontation / use of force",
        "pattern": r"\b(tased|taser|stun gun|officer[- ]involved|use of force|attacked (?:an? )?(?:officer|deputy|trooper)|assaulted (?:an? )?(?:officer|deputy|trooper)|struggle with|fought with (?:officers|deputies)|confrontation)\b",
        "query": '(tased OR taser OR "officer-involved" OR "attacked deputy" OR "assaulted officer")',
        "base_interest": 7,
    },
    "call_911": {
        "label": "Unusual 911 call",
        "pattern": r"\b(911 call|called 911|calling 911|911 dispatcher|911 caller|dispatch audio)\b",
        "query": '("911 call" OR "called 911") (police OR deputies) arrested',
        "base_interest": 6,
    },
    "arrest": {
        "label": "Dramatic arrest",
        "pattern": r"\b(arrested|arrest|taken into custody|apprehended|booked into|charged with)\b",
        "query": '(bodycam OR "body camera" OR "body cam") (police OR deputies OR troopers)',
        "base_interest": 4,
    },
}
CATEGORY_LABELS = {k: v["label"] for k, v in CATEGORIES.items()}
_CAT_RE = {k: re.compile(v["pattern"], re.I) for k, v in CATEGORIES.items()}

POLICE_RE = re.compile(
    r"\b(police|officers?|deputies|deputy|sheriff|troopers?|highway patrol|state patrol|swat|"
    r"arrest(?:ed|s)?|custody|law enforcement|k-?9|constable|marshals?|dps)\b", re.I)

# Stories that are about policy, courts or personnel rather than a filmable incident
OFF_TOPIC_RE = re.compile(
    r"\b(budget|hiring|recruit\w*|city council|commission meeting|ribbon cutting|promoted|retire[sd]?|"
    r"obituary|fundraiser|scholarship|award ceremony|job fair|toy drive|coffee with a cop|"
    r"election|campaign|op-ed|opinion:|editorial)\b", re.I)
COURT_STAGE_RE = re.compile(
    r"\b(sentenced|convicted|pleads? guilty|pleaded guilty|found guilty|acquitted|verdict|"
    r"trial (?:begins|starts|date)|jury selection|indicted|appeal)\b", re.I)


def detect_categories(text: str) -> list[str]:
    counts = []
    for key, rx in _CAT_RE.items():
        n = len(rx.findall(text))
        if n:
            counts.append((key, n))
    # 'arrest' is generic: only primary when nothing else matches
    counts.sort(key=lambda kv: (kv[0] == "arrest", -kv[1]))
    return [k for k, _ in counts]


def is_relevant(text: str) -> tuple[bool, str]:
    """Is this plausibly a filmable law-enforcement incident?"""
    if not POLICE_RE.search(text):
        return False, "no law-enforcement terms"
    cats = detect_categories(text)
    if not cats:
        return False, "no incident category terms"
    if OFF_TOPIC_RE.search(text) and cats == ["arrest"]:
        return False, "looks like a policy/personnel story"
    return True, "ok"


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
_STATE_NAME_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, US_STATES), key=len, reverse=True)) + r")\b")
_AP_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(map(re.escape, AP_ABBREVIATIONS)) + r")(?=[\s,)—-])")


def detect_states(text: str) -> list[str]:
    found: list[str] = []
    for m in _STATE_NAME_RE.finditer(text):
        name = m.group(1)
        tail = text[m.end(): m.end() + 12]
        # "Ohio State University" / "Washington Post" / "Florida Man" (meme) etc. still name the state,
        # but "Washington D.C." does not.
        if name == "Washington" and re.match(r",? D\.?C\.?", tail):
            continue
        found.append(name)
    for m in _AP_RE.finditer(text):
        found.append(AP_ABBREVIATIONS[m.group(1)])
    order = Counter(found)
    return [s for s, _ in order.most_common()]


def resolve_state(text: str, query_state: str | None) -> tuple[str | None, str]:
    states = detect_states(text)
    if query_state and query_state in states:
        return query_state, "named in source"
    if states:
        return states[0], "named in source"
    if query_state:
        return query_state, "search region (not stated in source)"
    return None, "unknown"


# ---------------------------------------------------------------------------
# Agencies
# ---------------------------------------------------------------------------
def _norm_apos(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'")


AGENCY_SUFFIX_RE = re.compile(
    r"\b(Police Department|Police Dept\.?|Sheriff's Office|Sheriff's Department|Sheriff Office|"
    r"Department of Public Safety|Public Safety Department|Highway Patrol|State Patrol|State Police|"
    r"Marshal's Office|Constable's Office|Police Bureau|Division of Police|Bureau of Police|PD)\b")
_PREFIX_STOP = {
    "the", "a", "an", "with", "from", "by", "of", "to", "said", "says", "and", "according",
    "deputies", "officers", "officer", "deputy", "troopers", "trooper", "detectives", "in", "for",
    "at", "on", "after", "when", "police", "sheriff", "local", "nearby", "say", "told", "while",
    "spokesperson", "spokesman", "spokeswoman", "release", "news", "press", "but", "as", "that",
    "this", "his", "her", "their", "is", "was", "were", "has", "had", "agency",
}
_NOT_PLACE = {"State", "Capitol", "Transit", "Airport", "Park", "School", "University", "Campus",
              "Tribal", "Port", "Metro", "Federal", "Military", "Border", "The", "Local", "Area",
              "Off-duty", "Former", "Retired", "Undercover", "Several", "Two", "Three", "Many", "Some",
              "Other", "Nearby", "Responding", "Arresting", "Our", "Their", "When", "After", "Where",
              "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "But",
              "Video", "Bodycam", "Body", "Watch", "Breaking", "Update", "Updated", "New", "Exclusive",
              "Man", "Woman", "Driver", "Suspect", "Florida Man", "January", "February", "March",
              "April", "May", "June", "July", "August", "September", "October", "November",
              "December", "Jan", "Feb", "Aug", "Sept", "Oct", "Nov", "Dec", "Officials", "Authorities"}


_ABBREV_OK = {"St.", "Ft.", "Mt.", "Pt."}


def _walk_prefix(text: str, start: int, max_words: int = 5) -> list[str]:
    raw = text[max(0, start - 80):start].split()
    picked: list[str] = []
    for tok in reversed(raw[-max_words:]):
        w = tok.strip("\"'()[]")
        if not w or not re.match(r"^[A-Za-z][A-Za-z.'\-]*$", w):
            break
        if w != tok.lstrip("\"'([") or (w.endswith(".") and w not in _ABBREV_OK):
            break  # punctuation boundary such as "said," / "Oct." / "18;"
        lw = w.lower()
        if lw in _PREFIX_STOP and not (lw == "of" and picked):
            break
        if lw == "of":  # "City of Miami Police Department", "University of Toledo Police"
            picked.append(w)
            continue
        if not w[0].isupper():
            break
        picked.append(w)
    while picked and picked[-1].lower() == "of":
        picked.pop()
    return list(reversed(picked))


def classify_agency(name: str) -> str:
    low = name.lower()
    if "sheriff" in low:
        return "sheriff"
    if any(t in low for t in ("highway patrol", "state patrol", "state police", "public safety")):
        return "state_patrol" if "department of public safety" not in low or "texas" in low else "police"
    if "marshal" in low or "constable" in low:
        return "constable"
    return "police"


def normalize_agency(name: str) -> str:
    n = _norm_apos(name).lower()
    n = re.sub(r"\bpd\b", "police department", n)
    n = n.replace("police dept.", "police department").replace("police dept", "police department")
    n = n.replace("sheriff office", "sheriff's office")
    n = re.sub(r"[^a-z0-9' ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def extract_agencies(text: str, state: str | None = None) -> list[tuple[str, str]]:
    """Return [(agency_name, basis)] in order of first mention."""
    text = _norm_apos(text)
    found: list[tuple[str, str]] = []

    for st, agencies in STATE_AGENCIES.items():
        for canonical, aliases in agencies:
            for alias in aliases:
                if re.search(r"\b" + re.escape(alias) + r"\b", text):
                    if len(alias) <= 4 and state and st != state:
                        continue  # bare abbreviation like CHP only counts in its own state
                    found.append((canonical, "named in source"))
                    break

    for m in AGENCY_SUFFIX_RE.finditer(text):
        suffix = m.group(1)
        prefix = _walk_prefix(text, m.start())
        if not prefix:
            continue
        if prefix[0] in _NOT_PLACE and len(prefix) == 1:
            continue
        while prefix and prefix[0] in _NOT_PLACE and prefix[0] not in ("State",):
            prefix = prefix[1:]
        if not prefix:
            continue
        if suffix == "PD":
            suffix = "Police Department"
        elif suffix.startswith("Police Dept"):
            suffix = "Police Department"
        elif suffix == "Sheriff Office":
            suffix = "Sheriff's Office"
        name = " ".join(prefix + [suffix])
        if suffix in ("Highway Patrol", "State Patrol", "State Police") and len(prefix) == 1 \
                and prefix[0] not in US_STATES:
            continue
        found.append((name, "named in source"))

    # Lower-confidence forms: "Tampa police said", "Hillsborough County deputies"
    for m in re.finditer(r"\b((?:[A-Z][a-z]+ ){0,2}[A-Z][a-z]+) police\b", text):
        place = m.group(1).strip()
        first = place.split()[0]
        if first in _NOT_PLACE or place in US_STATES or first.lower() in _PREFIX_STOP:
            continue
        if place.endswith("County"):
            continue
        found.append((f"{place} Police Department", "inferred from '<city> police' wording"))
    for m in re.finditer(r"\b((?:[A-Z][a-z]+ ){1,2}County) (?:deputies|deputy|sheriff)\b", text):
        county = m.group(1).strip()
        if county.split()[0] in _NOT_PLACE:
            continue
        found.append((f"{county} Sheriff's Office", "inferred from '<county> deputies' wording"))

    # de-duplicate by normalized name, keep strongest basis
    out: dict[str, tuple[str, str]] = {}
    for name, basis in found:
        key = normalize_agency(name)
        if key not in out or (out[key][1] != "named in source" and basis == "named in source"):
            out[key] = (name, basis)
    return list(out.values())


def pick_agency(texts: list[str], state: str | None) -> tuple[str | None, str]:
    """Pick the most-mentioned agency across a cluster of article texts."""
    tally: Counter = Counter()
    best_basis: dict[str, tuple[str, str]] = {}
    for t in texts:
        for name, basis in extract_agencies(t, state):
            key = normalize_agency(name)
            weight = 2 if basis == "named in source" else 1
            tally[key] += weight
            if key not in best_basis or basis == "named in source":
                best_basis[key] = (name, basis)
    if not tally:
        return None, "not stated in checked sources"
    # Prefer local agencies over the state patrol when tied
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], classify_agency(kv[0]) == "state_patrol"))
    return best_basis[ranked[0][0]]


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
def extract_location(text: str, state: str | None, agency: str | None) -> tuple[str | None, str | None, str]:
    """Return (city, county, basis)."""
    text = _norm_apos(text)
    city = county = None
    basis = "unknown"
    state_alts = []
    if state:
        state_alts = [re.escape(state)] + [re.escape(k) for k, v in AP_ABBREVIATIONS.items() if v == state]
    if state_alts:
        m = re.search(r"\b(?:in|near|of) ((?:[A-Z][a-z]+ ){0,2}[A-Z][a-z]+), (?:" + "|".join(state_alts) + r")", text)
        if m and m.group(1).split()[0] not in _NOT_PLACE:
            city, basis = m.group(1), "named in source"
    m = re.search(r"^([A-Z][A-Z .'-]{2,30})(?:,\s*[A-Z][A-Za-z.]+)?\s*(?:\([^)]*\))?\s*[—–-]{1,2}\s", text)
    if not city and m:
        city, basis = m.group(1).strip().title(), "article dateline"
    cm = re.search(r"\b((?:[A-Z][a-z]+ ){1,2})County\b", text)
    if cm and cm.group(1).split()[0] not in _NOT_PLACE:
        county = cm.group(1).strip() + " County"
        if basis == "unknown":
            basis = "county named in source"
    if agency and not city:
        low = agency.lower()
        if low.endswith("police department") and "county" not in low and "university" not in low:
            city = re.sub(r"^City of ", "", agency[: -len(" Police Department")]).strip()
            basis = "from agency name"
    if agency and not county and "county" in agency.lower():
        mm = re.match(r"(.*? County)", agency)
        if mm:
            county = mm.group(1)
    return city, county, basis


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTH_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.? (\d{1,2})(?:st|nd|rd|th)?\b(?:,? (\d{4}))?")
_WEEKDAY_RE = re.compile(
    r"\b(?:(last|early|late|on|this past) )?(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"(?: (morning|afternoon|evening|night))?\b")
_RELATIVE_RE = re.compile(
    r"\b(yesterday|last night|overnight|early this morning|this morning|this afternoon|earlier today|"
    r"tonight|last week|over the weekend|this weekend)\b", re.I)
_COURT_CONTEXT = re.compile(
    r"(court|hearing|scheduled|arraign|sentenc|trial|will appear|due back|bond|released from jail|"
    r"funeral|vigil|meeting|since|until|through|deadline|in \d{4}|years? ago)", re.I)


def local_day(published: datetime | None, state: str | None) -> date | None:
    if published is None:
        return None
    return (published + timedelta(hours=STATE_UTC_OFFSET.get(state or "", -5))).date()


def extract_incident_date(text: str, published: datetime | None, state: str | None = None
                          ) -> tuple[date | None, str, str]:
    """Return (incident_date, basis, evidence). Never guesses without textual evidence."""
    pub = local_day(published, state)
    if pub is None:
        return None, "unknown", ""
    text = _norm_apos(text)

    for m in _MONTH_RE.finditer(text):
        ctx = text[max(0, m.start() - 45): m.start()]
        if _COURT_CONTEXT.search(ctx):
            continue
        month = MONTHS[m.group(1)[:3].lower()]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else pub.year
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if not m.group(3) and d > pub:
            try:
                d = date(year - 1, month, day)
            except ValueError:
                continue
        if pub - timedelta(days=400) <= d <= pub:
            return d, "date stated in source", m.group(0)

    for m in _WEEKDAY_RE.finditer(text):
        ctx = text[max(0, m.start() - 45): m.start()]
        if _COURT_CONTEXT.search(ctx):
            continue
        target = WEEKDAYS.index(m.group(2).lower())
        delta = (pub.weekday() - target) % 7
        if m.group(1) and m.group(1).lower() in ("last",) and delta == 0:
            delta = 7
        return pub - timedelta(days=delta), "derived from weekday in source", m.group(0)

    m = _RELATIVE_RE.search(text)
    if m:
        word = m.group(1).lower()
        if word in ("yesterday", "last night", "overnight"):
            return pub - timedelta(days=1), "derived from relative wording", m.group(0)
        if word in ("last week",):
            return pub - timedelta(days=7), "approximate (\"last week\")", m.group(0)
        if word in ("over the weekend", "this weekend"):
            delta = (pub.weekday() - 5) % 7  # back to Saturday
            return pub - timedelta(days=delta), "approximate (weekend)", m.group(0)
        return pub, "derived from relative wording", m.group(0)
    return None, "not stated in checked sources", ""


DATE_BASIS_RANK = {
    "date stated in source": 4, "derived from weekday in source": 3,
    "derived from relative wording": 2, "approximate (weekend)": 1, "approximate (\"last week\")": 1,
}


# ---------------------------------------------------------------------------
# Footage signals
# ---------------------------------------------------------------------------
CAMERA = r"(?:body[- ]?cam(?:era)?s?|body[- ]worn cameras?|bodycams?|bwc|dash[- ]?cam(?:era)?s?|dashboard cameras?|cruiser cam(?:era)?|helicopter (?:video|footage)|aviation unit video)"
RELEASED_RE = re.compile(
    rf"(\b(?:released|releases|releasing|newly[- ]released|shared|posted|published|obtained)\b\W+(?:\w+\W+){{0,6}}?{CAMERA})"
    rf"|({CAMERA}\W+(?:\w+\W+){{0,2}}?(?:video|footage)\W+(?:\w+\W+){{0,3}}?(?:shows|showed|captures|captured|released|obtained|reveals))"
    rf"|(\b(?:watch|video)\W*:?\W*(?:\w+\W+){{0,3}}?{CAMERA})", re.I)
MENTION_RE = re.compile(CAMERA, re.I)
FILMABLE_CATEGORIES = {"pursuit", "dui", "standoff", "fleeing", "disorderly", "traffic_stop",
                       "rescue", "confrontation", "bizarre", "arrest", "call_911"}


def detect_bodycam(text: str, categories: list[str], agency: str | None) -> tuple[str, str]:
    from .models import BodycamStatus
    m = RELEASED_RE.search(text)
    if m:
        return BodycamStatus.RELEASED, _snippet(text, m.start(), m.end())
    m = MENTION_RE.search(text)
    if m:
        return BodycamStatus.MENTIONED, _snippet(text, m.start(), m.end())
    if agency and set(categories) & FILMABLE_CATEGORIES:
        return (BodycamStatus.LIKELY,
                "Estimate only: patrol officers at most US agencies wear body cameras and this incident "
                "involved direct officer contact. Not confirmed for this incident.")
    return BodycamStatus.UNKNOWN, ""


def _snippet(text: str, start: int, end: int, pad: int = 70) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    return ("..." if s else "") + text[s:e].strip() + ("..." if e < len(text) else "")


# ---------------------------------------------------------------------------
# Suspects
# ---------------------------------------------------------------------------
_NAME_AGE_RE = re.compile(r"\b([A-Z][a-z]+(?: [A-Z]\.)?(?: [A-Z][a-z'\-]+){1,2}),? (?:age )?(\d{2})\b,?")
_IDENTIFIED_RE = re.compile(r"\bidentified (?:him |her |the (?:man|woman|driver|suspect) )?as ([A-Z][a-z]+(?: [A-Z]\.)?(?: [A-Z][a-z'\-]+){1,2})")


def extract_suspects(text: str) -> list[str]:
    text = _norm_apos(text)
    names: list[str] = []
    for m in list(_NAME_AGE_RE.finditer(text)) + list(_IDENTIFIED_RE.finditer(text)):
        name = m.group(1)
        parts = name.split()
        if parts[0] in _NOT_PLACE or any(p in ("County", "Police", "Sheriff", "Department", "Office", "Highway")
                                         for p in parts):
            continue
        if parts[0] in US_STATES or name in US_STATES:
            continue
        if name not in names:
            names.append(name)
    return names[:3]


# ---------------------------------------------------------------------------
# Editorial risk flags
# ---------------------------------------------------------------------------
RISK_RULES = [
    ("minor", "Minor may be involved",
     r"\b(teens?|teenagers?|juveniles?|minors?|child(?:ren)?|kids?|boy|girl|students?|toddler|infant|baby|(?:1[0-7]|[1-9])-year-old)\b"),
    ("victim", "Crime victim / sensitive offense",
     r"\b(sexual(?:ly)? (?:assault|battery|abuse)\w*|rape|molest\w*|human trafficking|domestic (?:violence|battery|dispute)|victims?)\b"),
    ("graphic", "Possible graphic content / death or serious injury",
     r"\b(killed|dead|death|died|fatal(?:ly)?|murder\w*|homicide|stabb\w*|shot and killed|gunshot wounds?|critically injured|seriously injured)\b"),
    ("ongoing", "Ongoing investigation (release may be delayed)",
     r"\b(under investigation|investigation is ongoing|ongoing investigation|remains under investigation|active investigation|investigation continues|still investigating)\b"),
    ("privacy", "Privacy-sensitive (medical, mental health, home interior)",
     r"\b(mental health|mental crisis|baker act|suicid\w*|overdos\w*|medical emergency|inside (?:his|her|their|a) (?:home|residence|apartment|house)|hospital(?:ized)?)\b"),
    ("monetization", "YouTube ad-suitability risk (violence, weapons, nudity, drugs)",
     r"\b(shooting|shot|gun(?:fire|s)?|firearm|weapon|knife|naked|nude|drugs?|meth|fentanyl|cocaine|blood|graphic)\b"),
]
_RISK_RE = [(k, label, re.compile(p, re.I)) for k, label, p in RISK_RULES]


def risk_flags(text: str) -> list[dict]:
    flags = []
    for key, label, rx in _RISK_RE:
        m = rx.search(text)
        if m:
            flags.append({"flag": key, "label": label, "evidence": _snippet(text, m.start(), m.end(), 50),
                          "basis": "keyword match in source text"})
    return flags


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------
STOPWORDS = set("""
a an the and or but of to in on at for with from by as is are was were be been being it its this that
these those he she they his her their them who whom which what when where why how after before over
under into out up down off about than then so if not no yes new says said say man woman men women
police officer officers deputies deputy sheriff sheriffs office department arrested arrest arrests
county city state news report reports reported video watch update updates live local area two three
one year old years near during while also more just after amid following accused suspect suspects
""".split())


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", _norm_apos(text).lower())
    return {w.strip("'") for w in words if len(w) > 2 and w not in STOPWORDS and not w.isdigit()}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Candidate:
    """One article reduced to the fields used for clustering."""
    key: str
    title: str
    text: str
    published: datetime | None
    state: str | None
    agency: str | None
    city: str | None
    categories: list[str]
    toks: set[str] = field(default_factory=set)

    def __post_init__(self):
        if not self.toks:
            self.toks = tokens(self.title + " " + self.text[:300])


def same_incident(a: Candidate, b: Candidate) -> bool:
    if a.state and b.state and a.state != b.state:
        return False
    if a.published and b.published and abs((a.published - b.published).days) > 6:
        return False
    sim = jaccard(a.toks, b.toks)
    title_sim = jaccard(tokens(a.title), tokens(b.title))
    same_place = bool(
        (a.agency and b.agency and normalize_agency(a.agency) == normalize_agency(b.agency))
        or (a.city and b.city and a.city.lower() == b.city.lower()))
    shared_cat = bool(set(a.categories) & set(b.categories) - {"arrest"})
    if title_sim >= 0.5 or sim >= 0.45:
        return True
    if same_place and (sim >= 0.22 or title_sim >= 0.25):
        return True
    if same_place and shared_cat and sim >= 0.15:
        return True
    return False


def cluster(candidates: list[Candidate]) -> list[list[Candidate]]:
    """Greedy single-link clustering of articles that describe the same incident."""
    groups: list[list[Candidate]] = []
    for c in sorted(candidates, key=lambda c: c.published or datetime.min):
        for g in groups:
            if any(same_incident(c, other) for other in g):
                g.append(c)
                break
        else:
            groups.append([c])
    return groups
