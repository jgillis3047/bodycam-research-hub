"""Curated public-records-law summaries for bodycam requests.

These are informational summaries checked against the sources listed in `sources` (October 2026).
They are NOT legal advice. Laws change, so always confirm the current statute text and the agency's
own published procedure before relying on them.
"""
from __future__ import annotations

STATE_LAWS: dict[str, dict] = {
    "Florida": {
        "law_name": "Florida Public Records Act",
        "citation": "Fla. Stat. ch. 119 (esp. §119.07, §119.071(2)(l) body camera recordings)",
        "statute_url": "https://m.flsenate.gov/statutes/119.07",
        "response_time": "No fixed deadline: records must be produced within a reasonable time.",
        "bodycam_rules": [
            "Body camera recordings are generally public records.",
            "§119.071(2)(l): recordings taken inside a private residence, inside a health care, mental "
            "health or social services facility, or in a place where a person reasonably expects privacy "
            "are confidential/exempt (with limited exceptions for people depicted).",
            "Active criminal investigative/intelligence information is exempt until the case is no longer active (§119.071(2)(c)).",
        ],
        "fees": "Duplication cost; agencies may add a 'special service charge' for extensive use of "
                "staff or IT resources such as video review and redaction (§119.07(4)(d)). Request an estimate first.",
        "special_requirements": [],
        "request_window_days": None,
        "tips": ["Ask the agency for a written fee estimate before work begins.",
                 "Florida does not require you to state a purpose or give your name."],
        "sources": ["https://m.flsenate.gov/statutes/119.07",
                    "https://www.flsenate.gov/Session/Bill/2015/248/BillText/er/PDF"],
    },
    "Ohio": {
        "law_name": "Ohio Public Records Act",
        "citation": "Ohio Rev. Code §149.43 (restricted portions of body-worn/dashboard camera recordings: §149.43(A)(17))",
        "statute_url": "https://codes.ohio.gov/ohio-revised-code/section-149.43",
        "response_time": "Copies must be provided 'within a reasonable period of time'.",
        "bodycam_rules": [
            "Body-worn and dashboard camera recordings are public records, but listed 'restricted portions' "
            "(e.g., images of a deceased person, minors, sexual-offense victims, nudity, interiors of private "
            "residences, confidential informants) are redacted.",
            "Confidential law enforcement investigatory records (CLEIRs) can be withheld.",
        ],
        "fees": "Under HB 315 (signed Jan. 2, 2025) agencies MAY charge up to $75 per hour of video, capped at "
                "$750 per request, for producing body camera footage. Fees are at agency discretion.",
        "special_requirements": [],
        "request_window_days": None,
        "tips": ["Ask whether the agency charges the HB 315 video production fee before you submit.",
                 "Narrow the request to specific officers / time window to reduce cost."],
        "sources": ["https://codes.ohio.gov/ohio-revised-code/section-149.43/10-3-2023",
                    "https://www.13abc.com/2025/01/03/new-law-allows-police-agencies-charge-body-camera-footage/"],
    },
    "Wisconsin": {
        "law_name": "Wisconsin Public Records Law",
        "citation": "Wis. Stat. §§19.31-19.39; body cameras: Wis. Stat. §165.87 (2019 Wis. Act 108)",
        "statute_url": "https://docs.legis.wisconsin.gov/statutes/statutes/165/87/3",
        "response_time": "'As soon as practicable and without delay' (Wis. Stat. §19.35(4)).",
        "bodycam_rules": [
            "Body camera data is generally open to inspection under §19.35(1), subject to privacy protections.",
            "Minors, victims of sensitive or violent crimes, and people recorded where they reasonably "
            "expect privacy get privacy presumptions; faces may be blurred or redacted.",
            "Data must be retained at least 120 days after recording (longer if it shows a death, injury, "
            "custodial arrest, search, or use of force). Request early.",
        ],
        "fees": "Actual, necessary and direct cost of reproduction; location costs may be charged if over $50. "
                "Redaction time generally may not be charged.",
        "special_requirements": [],
        "request_window_days": 120,
        "tips": ["Submit within 120 days of the incident - routine footage may be purged after that.",
                 "The Wisconsin DOJ Office of Open Government publishes a compliance guide."],
        "sources": ["https://codes.findlaw.com/wi/police-regulations-ch-163-to-177/wi-st-165-87/",
                    "https://docs.legis.wisconsin.gov/2019/related/acts/108",
                    "https://www.wisdoj.gov/Open%20Government/PRL_guide.pdf"],
    },
    "Texas": {
        "law_name": "Texas Public Information Act + body camera statute",
        "citation": "Tex. Gov't Code ch. 552; body worn camera requests: Tex. Occ. Code §1701.661",
        "statute_url": "https://tcss.legis.texas.gov/resources/GV/pdf/GV.552.pdf",
        "response_time": "Body camera requests under §1701.661: agencies commonly cite 20 business days. "
                         "General PIA requests: produce promptly or seek an Attorney General ruling within 10 business days.",
        "bodycam_rules": [
            "Information relating to an ongoing criminal investigation can be withheld (Gov't Code §552.108).",
            "Recordings in private spaces have additional protections.",
        ],
        "fees": "Set by the agency under PIA cost rules; some agencies charge per recording plus per minute "
                "(example seen: $10 per recording + $1 per full minute). Ask for an estimate.",
        "special_requirements": [
            "Request must be in writing.",
            "Must include the DATE and APPROXIMATE TIME of the recording.",
            "Must include the SPECIFIC LOCATION where the recording occurred.",
            "Must include the NAME of one or more persons known to be a subject of the recording.",
            "Missing any of these can be grounds to deny the request.",
        ],
        "request_window_days": None,
        "tips": ["If you don't know the suspect's name, use the arrest report / jail booking record first.",
                 "Request the incident report number from the agency's records division."],
        "sources": ["https://lagovistatexas.gov/DocumentCenter/View/1093/Request-Body-Camera-Recordings-PDF",
                    "https://tcss.legis.texas.gov/resources/GV/pdf/GV.552.pdf"],
    },
    "Pennsylvania": {
        "law_name": "Pennsylvania Act 22 of 2017 (law enforcement audio/video recordings)",
        "citation": "42 Pa.C.S. Ch. 67A (Act 22 of 2017) - separate from the Right-to-Know Law (65 P.S. §67.101 et seq.)",
        "statute_url": "https://www.openrecords.pa.gov/",
        "response_time": "30 days from receipt (deemed denied if no written response).",
        "bodycam_rules": [
            "Bodycam/dashcam requests go through Act 22, NOT a normal Right-to-Know request.",
            "Can be denied if the recording contains potential evidence of a crime, investigative information, "
            "or confidential/victim information that reasonable redaction would not protect.",
        ],
        "fees": "Reasonable disclosure costs, paid when the recording is released.",
        "special_requirements": [
            "Must be submitted WITHIN 60 DAYS of the date the recording was made.",
            "Deliver in person or by CERTIFIED MAIL with proof of service to the agency's open-records officer.",
            "Must describe the specific incident including date, time and location.",
            "Must include a statement of your relationship to the incident.",
            "If recorded inside a residence: names of everyone present (or why they cannot be determined).",
        ],
        "request_window_days": 60,
        "tips": ["The 60-day clock is strict. Prioritise Pennsylvania cases quickly.",
                 "Many agencies post an Act 22 request form - use it when available."],
        "sources": ["https://www.police.psu.edu/requesting-body-worn-camera-footage",
                    "https://www.spotlightpa.org/news/2020/06/pennsylvania-body-cameras-footage-access/"],
    },
    "California": {
        "law_name": "California Public Records Act",
        "citation": "Cal. Gov. Code §7920.000 et seq.; critical-incident recordings: §7923.625",
        "statute_url": "https://california.public.law/codes/government_code_section_7923.625",
        "response_time": "10 days to determine whether records will be disclosed (extendable 14 days).",
        "bodycam_rules": [
            "Critical incidents (officer firearm discharge at a person, or force causing death/great bodily "
            "injury) must generally be released; delay up to 45 days allowed if disclosure would substantially "
            "interfere with an active investigation, with written reasons and an estimated date.",
            "Non-critical footage may be withheld as investigatory records; many agencies release it on request anyway.",
            "Privacy redactions (blurring) are allowed when they do not impair understanding of events.",
        ],
        "fees": "Direct cost of duplication; electronic-record programming/extraction costs may apply in some cases.",
        "special_requirements": [],
        "request_window_days": None,
        "tips": ["Mention §7923.625 if the incident involved a shooting or serious use of force.",
                 "Check the agency's 'critical incident videos' page - many post releases there."],
        "sources": ["https://california.public.law/codes/government_code_section_7923.625"],
    },
}

GENERIC_LAW = {
    "law_name": "State public records law (not yet curated in this app)",
    "citation": "Look up the state's public records / freedom of information statute.",
    "statute_url": None,
    "response_time": "Varies by state.",
    "bodycam_rules": ["Many states have bodycam-specific rules (request windows, privacy redaction, fees)."],
    "fees": "Unknown - ask the agency for an estimate.",
    "special_requirements": [],
    "request_window_days": None,
    "tips": ["Add a summary for this state by editing bch/state_laws.py."],
    "sources": [],
}


def law_for(state: str | None) -> dict:
    return STATE_LAWS.get(state or "", GENERIC_LAW)
