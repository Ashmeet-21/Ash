"""JD extraction: requirements, level, education and eligibility terms from posting text.

The rule-based extractor always runs. When Claude is available, Claude Haiku adds items the
rules missed (skills outside the taxonomy, education phrased oddly); its output is merged in,
never trusted blindly, and cached per JD hash by the caller.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from app.config import get_settings
from app.engine.skills import get_taxonomy
from app.llm import structured_call

REQUIRED_HEAD = re.compile(
    r"^\W*(requirements?|required|must[\s-]haves?|qualifications|minimum qualifications|basic qualifications|"
    r"what you(?:'ll| will)? (?:bring|need)|you have|who you are|what we(?:'re| are) looking for|skills|about you|"
    r"you should have|your background|key skills)\b",
    re.I,
)
PREFERRED_HEAD = re.compile(
    r"^\W*(nice[\s-]to[\s-]haves?|preferred|preferred qualifications|bonus(?: points)?|pluses|assets?|"
    r"good to have|desired|desirable|extra credit|it would be great if|additional qualifications)\b",
    re.I,
)
OTHER_HEAD = re.compile(
    r"^\W*(responsibilities|what you(?:'ll| will) do|the role|about (?:us|the (?:team|company|role))|"
    r"benefits|perks|what we offer|compensation|why join|our team|day to day|in this role)\b",
    re.I,
)
INLINE_PREFERRED = re.compile(r"\b(nice to have|is a plus|a plus|preferred|bonus|an asset|is an asset|desirable|ideally)\b", re.I)
INLINE_REQUIRED = re.compile(r"\b(must|required|requires|need to have|minimum|essential|mandatory)\b", re.I)

YEARS_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|to|–)\s*(\d{1,2})\s*)?\+?\s*(?:years?|yrs?)\b(?:\s+of)?(?:\s+\w+){0,4}?\s+(?:experience|exp\b)",
    re.I,
)
EDU_LEVELS = [
    ("phd", re.compile(r"\b(ph\.?d|doctorate|doctoral)\b", re.I)),
    ("master", re.compile(r"\b(master'?s|m\.?sc?\b|m\.?eng|mba|m\.?tech)\b", re.I)),
    ("bachelor", re.compile(r"\b(bachelor'?s?|b\.?sc?\b|b\.?a\.?\b|b\.?eng|b\.?tech|b\.?e\.?\b|undergraduate degree|university degree|4-year degree|degree in)\b", re.I)),
    ("diploma", re.compile(r"\b(diploma|associate'?s? degree|certificate program)\b", re.I)),
]
EDU_RANK = {"diploma": 1, "associate": 1, "bachelor": 2, "master": 3, "phd": 4}
EDU_FIELDS = re.compile(
    r"\b(computer science|computer engineering|software engineering|information technology|information systems|"
    r"cyber ?security|information security|electrical engineering|data science|mathematics|statistics|engineering)\b",
    re.I,
)
SALARY_RE = re.compile(
    r"(?P<cur>CAD|USD|AED|INR|C\$|US\$|\$|₹|Rs\.?)\s?(?P<lo>\d[\d,]*(?:\.\d+)?)\s?(?P<lok>[kK])?\s*(?:-|–|to)\s*(?:CAD|USD|AED|INR|C\$|US\$|\$|₹|Rs\.?)?\s?(?P<hi>\d[\d,]*(?:\.\d+)?)\s?(?P<hik>[kK])?"
    r"|(?P<lpa_lo>\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(?P<lpa_hi>\d+(?:\.\d+)?)\s*(?:LPA|lakhs?)",
    re.I,
)
LOCATION_LINE = re.compile(r"^\W*(?:location|based in|office|work location)s?\s*[:\-]\s*(.+)$", re.I | re.M)
REMOTE_RE = re.compile(r"\b(fully remote|remote[- ]first|100% remote|remote position|work from home|remote \(|remote,|remote$|remote-friendly|remote ok)\b", re.I | re.M)

SENIORITY = [
    ("co-op", re.compile(r"\b(co-?op|intern(ship)?|placement|work term)\b", re.I)),
    ("new-grad", re.compile(r"\b(new grad(uate)?|graduate|entry[- ]level|early career|university grad|campus|fresher|class of 20\d\d)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr\.?|associate|level i\b|l1\b|analyst i\b|engineer i\b)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|architect)\b", re.I)),
]


@dataclass
class Requirement:
    item: str
    kind: str  # hard | soft | education | eligibility
    required: bool
    mentions: int = 1
    in_taxonomy: bool = True


@dataclass
class Extraction:
    title: str
    company: str | None
    location: str | None
    remote: bool
    seniority: str | None
    requirements: list[Requirement]
    min_years: float | None
    education: dict
    salary: dict | None
    keyword_counts: dict[str, int]
    sources: list[str] = field(default_factory=lambda: ["rules"])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Extraction":
        d = dict(d)
        d["requirements"] = [Requirement(**r) for r in d["requirements"]]
        return cls(**d)

    def hard(self, required: bool | None = None) -> list[Requirement]:
        return [r for r in self.requirements if r.kind == "hard" and (required is None or r.required == required)]

    def soft(self) -> list[Requirement]:
        return [r for r in self.requirements if r.kind == "soft"]


def jd_hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text.strip().lower()).encode()).hexdigest()


def _sections(text: str) -> list[tuple[str, str]]:
    """Split JD into (section_kind, line) where section_kind is required | preferred | other | intro."""
    out: list[tuple[str, str]] = []
    current = "intro"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_heading = len(line) < 80 and (line.endswith(":") or not re.search(r"[.!?]$", line)) and not line.startswith(("-", "*", "•"))
        if is_heading:
            if PREFERRED_HEAD.search(line):
                current = "preferred"
                continue
            if REQUIRED_HEAD.search(line):
                current = "required"
                continue
            if OTHER_HEAD.search(line):
                current = "other"
                continue
        out.append((current, line))
    return out


def _seniority(title: str) -> str | None:
    for label, pat in SENIORITY:
        if pat.search(title):
            return label
    return None


def _salary(text: str) -> dict | None:
    m = SALARY_RE.search(text)
    if not m:
        return None
    if m.group("lpa_lo"):
        return {"min": float(m.group("lpa_lo")) * 100_000, "max": float(m.group("lpa_hi")) * 100_000, "currency": "INR"}
    cur = m.group("cur").upper().replace("RS.", "INR").replace("RS", "INR").replace("₹", "INR").replace("C$", "CAD").replace("US$", "USD").replace("$", "USD?")
    lo = float(m.group("lo").replace(",", "")) * (1000 if m.group("lok") else 1)
    hi = float(m.group("hi").replace(",", "")) * (1000 if m.group("hik") or (m.group("lok") and not m.group("hik")) else 1)
    if hi < 100 and lo < 100:  # hourly or noise like "1 - 2"
        if hi < 15:
            return None
    return {"min": lo, "max": hi, "currency": cur}


def _education(sections: list[tuple[str, str]]) -> dict:
    level = None
    fields: set[str] = set()
    required = False
    for kind, line in sections:
        for lvl, pat in EDU_LEVELS:
            if pat.search(line):
                if level is None or EDU_RANK[lvl] < EDU_RANK[level]:
                    level = lvl
                if kind != "preferred" and not INLINE_PREFERRED.search(line):
                    required = True
        if level or re.search(r"\bdegree\b", line, re.I):
            fields.update(f.lower() for f in EDU_FIELDS.findall(line))
    return {"required": required, "level": level, "fields": sorted(fields)}


def _min_years(sections: list[tuple[str, str]]) -> float | None:
    best: float | None = None
    for kind, line in sections:
        if kind == "preferred" or INLINE_PREFERRED.search(line):
            continue
        for m in YEARS_RE.finditer(line):
            years = float(m.group(1))
            if years > 15:
                continue
            best = years if best is None else max(best, years)
    return best


def extract_rules(jd_text: str, title: str = "", company: str | None = None, location: str | None = None) -> Extraction:
    tax = get_taxonomy()
    sections = _sections(jd_text)
    title = title or (sections[0][1] if sections and len(sections[0][1]) < 100 else "")

    per_skill: dict[str, dict] = {}
    all_counts: Counter[str] = Counter()
    for kind, line in sections:
        found = tax.find(line)
        if not found:
            continue
        all_counts.update(found)
        line_pref = kind == "preferred" or bool(INLINE_PREFERRED.search(line))
        line_req = kind == "required" or bool(INLINE_REQUIRED.search(line))
        for name, n in found.items():
            entry = per_skill.setdefault(name, {"req": False, "pref": False, "other": 0})
            if line_req and not line_pref:
                entry["req"] = True
            elif line_pref:
                entry["pref"] = True
            else:
                entry["other"] += n
    all_counts.update(tax.find(title))

    requirements: list[Requirement] = []
    for name, e in per_skill.items():
        # Skills named only in responsibilities or intro count as required when repeated.
        required = e["req"] or (not e["pref"] and e["other"] >= 2) or (not e["pref"] and not e["req"] and len(per_skill) <= 6)
        requirements.append(Requirement(item=name, kind=tax.kind(name), required=required, mentions=all_counts[name]))

    edu = _education(sections)
    if edu["level"]:
        requirements.append(Requirement(item=f"{edu['level']} degree", kind="education", required=edu["required"]))

    if not location:
        m = LOCATION_LINE.search(jd_text)
        location = m.group(1).strip()[:200] if m else None
    remote = bool(REMOTE_RE.search(jd_text)) or bool(location and "remote" in location.lower()) or "remote" in title.lower()

    return Extraction(
        title=title,
        company=company,
        location=location,
        remote=remote,
        seniority=_seniority(title),
        requirements=requirements,
        min_years=_min_years(sections),
        education=edu,
        salary=_salary(jd_text),
        keyword_counts=dict(all_counts),
    )


LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "remote": {"type": "boolean"},
        "min_years_experience": {"type": ["number", "null"]},
        "education_required": {"type": "boolean"},
        "education_level": {"type": ["string", "null"], "enum": ["diploma", "bachelor", "master", "phd", None]},
        "required_hard_skills": {"type": "array", "items": {"type": "string"}},
        "preferred_hard_skills": {"type": "array", "items": {"type": "string"}},
        "soft_skills": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "company", "location", "remote", "min_years_experience", "education_required",
        "education_level", "required_hard_skills", "preferred_hard_skills", "soft_skills",
    ],
    "additionalProperties": False,
}

LLM_SYSTEM = (
    "You extract structured requirements from job descriptions for a resume matching tool. "
    "List each concrete skill, tool, technology, framework, certification or domain once, using its common short name "
    "(for example 'Python', 'Splunk', 'Kubernetes', 'Security+'). A skill is required only when the posting presents it as "
    "required; anything described as preferred, a plus, nice to have or an asset is preferred. Use null when the posting does "
    "not state a value. Do not infer requirements the text does not state."
)


def extract_llm(jd_text: str) -> dict | None:
    settings = get_settings()
    return structured_call(
        model=settings.extract_model,
        system=LLM_SYSTEM,
        prompt=f"<job_description>\n{jd_text[:30000]}\n</job_description>",
        schema=LLM_SCHEMA,
        max_tokens=4000,
        effort="low",
    )


def merge_llm(ex: Extraction, data: dict) -> Extraction:
    """Add what Claude found that the rules missed. Rule results win on conflicts."""
    tax = get_taxonomy()
    have = {r.item for r in ex.requirements}
    for items, required, default_kind in (
        (data.get("required_hard_skills", []), True, "hard"),
        (data.get("preferred_hard_skills", []), False, "hard"),
        (data.get("soft_skills", []), True, "soft"),
    ):
        for raw in items:
            raw = raw.strip()
            if not raw or len(raw) > 60:
                continue
            canon = tax.canonical(raw)
            name = canon or raw
            if name in have:
                continue
            have.add(name)
            kind = tax.kind(canon) if canon else default_kind
            ex.requirements.append(Requirement(item=name, kind=kind, required=required, mentions=1, in_taxonomy=canon is not None))
    ex.company = ex.company or data.get("company")
    ex.location = ex.location or data.get("location")
    ex.remote = ex.remote or bool(data.get("remote"))
    if ex.min_years is None and data.get("min_years_experience") is not None:
        ex.min_years = float(data["min_years_experience"])
    if not ex.education.get("level") and data.get("education_level"):
        ex.education = {"required": bool(data.get("education_required")), "level": data["education_level"], "fields": ex.education.get("fields", [])}
        ex.requirements.append(Requirement(item=f"{data['education_level']} degree", kind="education", required=ex.education["required"]))
    ex.sources = [*ex.sources, "claude"]
    return ex


def extract(jd_text: str, title: str = "", company: str | None = None, location: str | None = None, use_llm: bool = True) -> Extraction:
    ex = extract_rules(jd_text, title=title, company=company, location=location)
    if use_llm:
        data = extract_llm(jd_text)
        if data:
            ex = merge_llm(ex, data)
    return ex
