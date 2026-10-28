"""Knockout risks and missing-info flags. Reported separately from the score, never averaged in."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date

from app.engine.extract import EDU_RANK, Extraction
from app.facts import Facts
from app.regions import get_regions

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"

GRAD_WINDOW = re.compile(
    rf"(?:graduat\w*|degree\s+completion|complet\w+\s+(?:your|a|their)\s+degree)[^.\n]{{0,60}}?(?:between|from)\s+{MONTH_RE}\s+(\d{{4}})\s+(?:and|to|-|–)\s+{MONTH_RE}\s+(\d{{4}})",
    re.I,
)
GRAD_BY = re.compile(
    rf"(?:graduat\w*|degree)[^.\n]{{0,40}}?(?:by|before|no later than|prior to)\s+(?:{MONTH_RE}\s+)?(\d{{4}})", re.I
)
CLASS_OF = re.compile(r"\b(?:class of|graduating in|graduation (?:year|date)(?: of)?:?|grads? of)\s*(?:the\s+)?(?:year\s+)?(20\d\d)(?:\s*(?:or|/|and|,)\s*(20\d\d))?", re.I)
RECENT_GRAD = re.compile(r"graduated\s+(?:with)?in\s+the\s+(?:last|past)\s+(\d+|one|two|three)\s+(months?|years?)", re.I)
ENROLLED = re.compile(r"\b(must be|currently)\s+(?:currently\s+)?(enrolled|a student|pursuing)\b|returning to school|return to (?:your )?studies", re.I)

NO_SPONSOR = re.compile(
    r"(no|not|unable to|cannot|can't|won't|will not|do not|does not)\s+(?:\w+\s+){0,3}(sponsor|sponsorship|provide (?:visa|work permit))|"
    r"without (?:the need for |requiring )?(?:visa |employer )?sponsorship|sponsorship (?:is )?not (?:available|provided|offered)",
    re.I,
)
WORK_AUTH = re.compile(
    r"(legally (?:authorized|entitled|eligible) to work|must (?:be|have) (?:authorized|eligible|the right) to work|valid work (?:permit|authorization|visa)|"
    r"citizens? or permanent residents?|canadian citizen|u\.?s\.? citizen|security clearance|(?:secret|reliability|enhanced) clearance|uae national|emirati)",
    re.I,
)
CLEARANCE = re.compile(r"\b(security clearance|secret clearance|top secret|reliability status|enhanced reliability|nv1|baseline clearance)\b", re.I)
RELOCATION = re.compile(r"\b(relocat\w+|on-?site|in[- ]office|hybrid|\d\s+days?\s+(?:a|per)\s+week in (?:the )?office)\b", re.I)
LANGUAGE = re.compile(
    r"\b(french|bilingual|arabic|mandarin|cantonese|spanish|german|japanese|hindi|punjabi|korean)\b[^.\n]{0,40}\b(required|mandatory|must|essential|fluen\w+|proficien\w+|is an asset|preferred|plus)?",
    re.I,
)
TERM = re.compile(r"\b(\d{1,2})[\s-]*(?:to\s*\d{1,2}[\s-]*)?month\b[^.\n]{0,30}?\b(co-?op|internship|intern|term|work term|placement|contract|position)", re.I)
TERM_RANGE = re.compile(r"\b(\d{1,2})\s*(?:-|–|to|or)\s*(\d{1,2})[\s-]*months?\b[^.\n]{0,30}?\b(co-?op|internship|term|work term|placement|contract)", re.I)


@dataclass
class FlagOut:
    type: str
    severity: str  # block | warn | info
    message: str
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


def _snippet(text: str, m: re.Match, pad: int = 60) -> str:
    s, e = max(0, m.start() - pad), min(len(text), m.end() + pad)
    return ("..." if s else "") + " ".join(text[s:e].split()) + ("..." if e < len(text) else "")


def _month(token: str) -> int:
    return MONTHS.get(token[:3].lower(), 6)


def check_graduation(text: str, facts: Facts) -> list[FlagOut]:
    grad = facts.profile.graduation
    flags: list[FlagOut] = []
    for m in GRAD_WINDOW.finditer(text):
        start = date(int(m.group(2)), _month(m.group(1)), 1)
        end = date(int(m.group(4)), _month(m.group(3)), 28)
        if not (start <= grad <= end):
            flags.append(FlagOut("grad_window", "block", f"Graduation window {start:%b %Y} to {end:%b %Y} excludes your {grad:%b %Y} date.", _snippet(text, m)))
        else:
            flags.append(FlagOut("grad_window", "info", f"Your {grad:%b %Y} graduation fits the stated window.", _snippet(text, m)))
        return flags
    for m in CLASS_OF.finditer(text):
        years = {int(y) for y in m.groups() if y}
        if grad.year not in years:
            flags.append(FlagOut("grad_window", "block", f"Posting targets graduates of {', '.join(map(str, sorted(years)))}; you graduate in {grad.year}.", _snippet(text, m)))
        return flags
    for m in GRAD_BY.finditer(text):
        by_year = int(m.group(2))
        if grad.year > by_year:
            flags.append(FlagOut("grad_window", "block", f"Requires graduation by {by_year}; you graduate {grad:%b %Y}.", _snippet(text, m)))
        return flags
    for m in RECENT_GRAD.finditer(text):
        flags.append(FlagOut("grad_window", "warn", "Posting wants recent graduates; check whether a future graduation date qualifies.", _snippet(text, m)))
        return flags
    return flags


def check_enrollment(text: str, ex: Extraction, facts: Facts, today: date) -> list[FlagOut]:
    m = ENROLLED.search(text)
    if not m:
        return []
    if facts.profile.graduation < today:
        return [FlagOut("enrollment", "block", "Requires current enrollment; your graduation date has passed.", _snippet(text, m))]
    return [FlagOut("enrollment", "info", "Requires current enrollment or return to studies after the term.", _snippet(text, m))]


def check_sponsorship(text: str, job_regions: list[str], facts: Facts) -> list[FlagOut]:
    flags: list[FlagOut] = []
    needs = [r for r in job_regions if facts.profile.needs_sponsorship.get(r)]
    m = NO_SPONSOR.search(text)
    if m:
        sev = "block" if needs else "info"
        msg = (
            f"States no sponsorship and you would need it for {', '.join(needs)}."
            if needs
            else "States no sponsorship; fine if your work authorization covers this location."
        )
        flags.append(FlagOut("sponsorship", sev, msg, _snippet(text, m)))
    m = WORK_AUTH.search(text)
    if m:
        flags.append(FlagOut("work_authorization", "warn" if needs else "info", "Has a work authorization requirement; confirm your status meets it.", _snippet(text, m)))
    m = CLEARANCE.search(text)
    if m:
        flags.append(FlagOut("clearance", "warn", "Requires a security clearance, which often needs citizenship or years of residency.", _snippet(text, m)))
    return flags


def check_location(ex: Extraction, job_regions: list[str], facts: Facts, text: str) -> list[FlagOut]:
    flags: list[FlagOut] = []
    open_to = set(facts.profile.open_to_regions)
    if ex.remote and "remote" in open_to:
        return flags
    if job_regions and not (set(job_regions) & open_to):
        flags.append(FlagOut("location", "block", f"Location ({ex.location}) is outside your target regions.", ex.location or ""))
    elif not job_regions and ex.location:
        flags.append(FlagOut("location", "warn", f"Location '{ex.location}' does not match any target region; relocation may be needed.", ex.location))
    m = RELOCATION.search(text)
    if m and "relocat" in m.group(1).lower():
        flags.append(FlagOut("relocation", "info", "Mentions relocation; check whether support is offered.", _snippet(text, m)))
    return flags


def check_language(text: str, facts: Facts) -> list[FlagOut]:
    spoken = {l.lower() for l in facts.profile.languages}
    flags: list[FlagOut] = []
    seen: set[str] = set()
    for m in LANGUAGE.finditer(text):
        lang = m.group(1).lower()
        if lang == "bilingual":
            # Bilingual roles in Canada almost always mean English and French.
            lang = "french" if "french" not in spoken else "bilingual"
            if lang == "bilingual":
                continue
        if lang in spoken or lang in seen:
            continue
        seen.add(lang)
        strength = (m.group(2) or "").lower()
        optional = any(w in strength for w in ("asset", "preferred", "plus"))
        if not strength:
            ctx = text[m.start(): m.end() + 80].lower()
            if not re.search(r"required|mandatory|must|essential|fluen|proficien", ctx):
                continue
        flags.append(FlagOut("language", "info" if optional else "block", f"{lang.title()} {'is an asset' if optional else 'appears required'} and is not in your languages.", _snippet(text, m)))
    return flags


def check_term(text: str, facts: Facts) -> list[FlagOut]:
    limit = facts.profile.max_term_months
    if not limit:
        return []
    for m in TERM_RANGE.finditer(text):
        lo = int(m.group(1))
        if lo > limit:
            return [FlagOut("term_length", "block", f"Term of {lo}+ months exceeds your {limit}-month availability.", _snippet(text, m))]
        return []
    for m in TERM.finditer(text):
        months = int(m.group(1))
        if months > limit:
            return [FlagOut("term_length", "block", f"{months}-month term exceeds your {limit}-month availability.", _snippet(text, m))]
        return []
    return []


def check_experience(ex: Extraction, facts: Facts) -> list[FlagOut]:
    if ex.min_years is None:
        return []
    have = facts.profile.years_experience
    if ex.min_years > have + 1.5:
        return [FlagOut("years_required", "block", f"Asks for {ex.min_years:g}+ years of experience; you have about {have:g}.", f"{ex.min_years:g}+ years")]
    if ex.min_years > have:
        return [FlagOut("years_required", "warn", f"Asks for {ex.min_years:g} years; you have about {have:g}. Often flexible for junior roles.", f"{ex.min_years:g} years")]
    return []


def check_education(ex: Extraction, facts: Facts) -> list[FlagOut]:
    lvl = ex.education.get("level")
    if not lvl or not ex.education.get("required"):
        return []
    mine = EDU_RANK.get(facts.profile.degree.level, 2)
    if EDU_RANK[lvl] > mine:
        return [FlagOut("education", "block", f"Requires a {lvl} degree; you are completing a {facts.profile.degree.level}.", lvl)]
    return []


def check_seniority(ex: Extraction) -> list[FlagOut]:
    if ex.seniority == "senior":
        return [FlagOut("seniority", "warn", "Title reads as a senior-level role.", ex.title)]
    return []


def check_missing(ex: Extraction) -> list[FlagOut]:
    flags = []
    if not ex.company:
        flags.append(FlagOut("missing_company", "info", "No company name; possibly a recruiter or agency posting.", ""))
    if not ex.salary:
        flags.append(FlagOut("missing_salary", "info", "No salary range listed.", ""))
    if not ex.location and not ex.remote:
        flags.append(FlagOut("missing_location", "info", "No location listed.", ""))
    return flags


def check_all(jd_text: str, ex: Extraction, facts: Facts, today: date | None = None) -> list[FlagOut]:
    today = today or date.today()
    job_regions = get_regions().match(" ".join(x for x in [ex.location or "", ex.title] if x))
    if ex.remote:
        job_regions = sorted(set(job_regions) | {"remote"})
    flags = [
        *check_graduation(jd_text, facts),
        *check_enrollment(jd_text, ex, facts, today),
        *check_sponsorship(jd_text, job_regions, facts),
        *check_location(ex, job_regions, facts, jd_text),
        *check_language(jd_text, facts),
        *check_term(jd_text, facts),
        *check_experience(ex, facts),
        *check_education(ex, facts),
        *check_seniority(ex),
        *check_missing(ex),
    ]
    order = {"block": 0, "warn": 1, "info": 2}
    return sorted(flags, key=lambda f: order[f.severity])
