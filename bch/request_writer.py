"""Draft public records requests for bodycam/dashcam footage. Drafts only - never submitted automatically."""
from __future__ import annotations

from datetime import date

from .state_laws import law_for

PLACEHOLDER = "[FILL IN: {}]"


def _fmt_date(d: date | None) -> str:
    return d.strftime("%B %d, %Y").replace(" 0", " ") if d else PLACEHOLDER.format("incident date")


def draft_request(*, case: dict, agency_name: str | None, contact: dict, budget: float | None,
                  include: dict | None = None, approx_time: str = "", report_number: str = "",
                  subject_names: list[str] | None = None, today: date | None = None) -> str:
    """Return a plain-text records request letter.

    `case` keys used: headline, state, city, county, incident_date, location_text, sources (list of urls)
    `include` toggles: bodycam, dashcam, audio_911, cad, incident_report, photos
    """
    include = include or {"bodycam": True, "dashcam": True, "audio_911": False, "cad": False,
                          "incident_report": True, "photos": False}
    today = today or date.today()
    state = case.get("state")
    law = law_for(state)
    agency = agency_name or PLACEHOLDER.format("agency name")
    names = subject_names if subject_names is not None else case.get("suspect_names") or []
    place = ", ".join(x for x in [case.get("location_text") or case.get("city"), case.get("county"), state] if x) \
        or PLACEHOLDER.format("location")
    time_txt = approx_time or PLACEHOLDER.format("approximate time")
    who = contact.get("name") or PLACEHOLDER.format("your name")

    items = []
    if include.get("bodycam"):
        items.append("All body-worn camera (BWC) recordings from every officer/deputy who responded to or "
                     "participated in the incident, from activation to deactivation.")
    if include.get("dashcam"):
        items.append("All in-car / dashboard camera recordings from every responding vehicle, plus any "
                     "aviation-unit or drone video, if it exists.")
    if include.get("audio_911"):
        items.append("Audio of any 911 calls and radio/dispatch traffic related to the incident.")
    if include.get("cad"):
        items.append("The Computer-Aided Dispatch (CAD) report / call log for the incident.")
    if include.get("incident_report"):
        items.append("The incident/offense report and arrest affidavit (public portions).")
    if include.get("photos"):
        items.append("Scene photographs released to the public.")
    item_lines = "\n".join(f"  {i}. {t}" for i, t in enumerate(items, 1))

    special = ""
    if state == "Texas":
        special = (
            "\nThis request is made under Texas Occupations Code §1701.661 and the Public Information Act. "
            "As required, it includes:\n"
            f"  - Date and approximate time of the recording: {_fmt_date(case.get('incident_date'))}, {time_txt}\n"
            f"  - Specific location: {place}\n"
            f"  - Person(s) who are a subject of the recording: "
            f"{', '.join(names) if names else PLACEHOLDER.format('name of at least one person recorded (required in Texas)')}\n")
    elif state == "Pennsylvania":
        special = (
            "\nThis is a request under 42 Pa.C.S. Chapter 67A (Act 22 of 2017) for audio/video recordings made "
            "by a law enforcement agency. It is being delivered within 60 days of the recording date.\n"
            f"  - Date, time and location of the event: {_fmt_date(case.get('incident_date'))}, {time_txt}, {place}\n"
            f"  - My relationship to the incident: {PLACEHOLDER.format('e.g. independent journalist / documentary publisher with no personal involvement')}\n"
            "  - If any recording was made inside a residence, the names of all persons present are: "
            f"{PLACEHOLDER.format('names, or explain why they cannot be determined')}\n"
            "NOTE: Deliver this in person or by certified mail with proof of service to the Open Records Officer.\n")
    elif state == "California":
        special = ("\nIf any recording depicts a 'critical incident' as defined in Government Code §7923.625 "
                   "(discharge of a firearm at a person, or use of force resulting in death or great bodily "
                   "injury), I request release within the timelines that section requires, or a written "
                   "explanation of any delay with an estimated release date.\n")
    elif state == "Ohio":
        special = ("\nI understand restricted portions under R.C. 149.43(A)(17) may be redacted; please release "
                   "the remaining portions. If your agency charges a fee for producing body camera footage, "
                   "please send an estimate before starting work.\n")
    elif state == "Wisconsin":
        special = ("\nPlease preserve these recordings while this request is pending (Wis. Stat. §165.87 retention), "
                   "and redact rather than withhold if any privacy interest applies.\n")
    elif state == "Florida":
        special = ("\nIf any portion is claimed exempt (e.g., Fla. Stat. §119.071(2)(l)), please cite the specific "
                   "exemption, redact only that portion, and release the remainder.\n")

    budget_line = (f"Please contact me before incurring fees above ${budget:,.2f}. "
                   if budget else "Please provide a fee estimate before incurring any costs. ")

    sources = case.get("sources") or []
    src_line = ""
    if sources:
        src_line = "\nPublic reporting about the incident (for identification only):\n" + \
                   "\n".join(f"  - {u}" for u in sources[:3]) + "\n"

    contact_lines = "\n".join(x for x in [
        who, contact.get("organization", ""), contact.get("address", ""),
        contact.get("email", ""), contact.get("phone", "")] if x)

    return f"""{today.strftime('%B %d, %Y').replace(' 0', ' ')}

To: Records Custodian / Public Records Unit
{agency}

RE: Public records request - {law['law_name']} ({law['citation']})
Incident: {case.get('headline', '').strip()}

Dear Records Custodian,

Pursuant to the {law['law_name']}, I request copies of the following records relating to the incident on
{_fmt_date(case.get('incident_date'))} at approximately {time_txt}, at or near {place}
{f"(Report/case number: {report_number})" if report_number else "(Report/case number: " + PLACEHOLDER.format("if known") + ")"}:

{item_lines}
{special}{src_line}
I request the recordings in their native digital format (or a standard format such as MP4), delivered
electronically by download link or e-mail where possible. If any portion is withheld or redacted, please cite
the specific legal exemption for each withholding and release all reasonably segregable portions.

{budget_line}If you are not the custodian of these records, please forward this request to the correct
custodian or let me know who that is.

Thank you for your assistance. I look forward to your response{" within the 30 days Chapter 67A provides" if state == "Pennsylvania" else ""}.

Sincerely,

{contact_lines}
"""
