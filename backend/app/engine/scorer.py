"""JobMatch score (0-100) and the gap classification that drives tailoring.

Weights come from the design doc. They are a starting point, tuned against the labeled
golden set (scripts/evaluate.py). A component the JD gives no basis for (for example,
education when no degree is mentioned) is left out and the rest are renormalized.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from app.engine.extract import EDU_RANK, Extraction, Requirement
from app.engine.semantic import similarity
from app.engine.skills import get_taxonomy
from app.facts import Facts

WEIGHTS = {
    "hard_skills": 40,
    "semantic": 20,
    "title_level": 15,
    "keywords": 10,
    "format": 10,
    "education": 5,
}
KEYWORD_CAP = 3  # a term counts at most this many times, so stuffing doesn't help
NO_ADJACENCY_FAMILIES = {"soft", "certs"}
TITLE_NOISE = re.compile(
    r"\b(senior|sr|junior|jr|intern(ship)?|co-?op|new grad(uate)?|graduate|entry[- ]level|early career|i{1,3}|iv|l[1-4]|"
    r"remote|hybrid|on-?site|contract|full[- ]time|part[- ]time|summer|fall|winter|spring|20\d\d|\d+\s*months?)\b",
    re.I,
)


@dataclass
class Component:
    key: str
    weight: int
    value: float | None  # 0..1, or None when not applicable
    detail: str

    @property
    def points(self) -> float | None:
        return None if self.value is None else round(self.weight * self.value, 1)


@dataclass
class GapItem:
    item: str
    kind: str
    required: bool
    status: str  # shown | hidden | adjacent | gap
    evidence: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class ScoreResult:
    total: float
    components: list[Component]
    gaps: list[GapItem]
    semantic_backend: str

    def breakdown(self) -> dict:
        return {
            c.key: {"weight": c.weight, "value": None if c.value is None else round(c.value, 3), "points": c.points, "detail": c.detail}
            for c in self.components
        }

    def gaps_dict(self) -> dict:
        out: dict[str, list] = {"shown": [], "hidden": [], "adjacent": [], "gap": []}
        for g in self.gaps:
            out[g.status].append(asdict(g))
        return out


def _present(req: Requirement, resume_skills: set[str], resume_lower: str) -> bool:
    if req.in_taxonomy:
        return req.item in resume_skills
    return bool(re.search(rf"(?<!\w){re.escape(req.item.lower())}(?!\w)", resume_lower))


def classify_gaps(ex: Extraction, resume_text: str, facts: Facts) -> list[GapItem]:
    """Covered and shown / covered but hidden / adjacent / true gap, per the improvement engine."""
    tax = get_taxonomy()
    resume_skills = set(tax.find(resume_text))
    resume_lower = resume_text.lower()
    pool = facts.pool_names()
    out: list[GapItem] = []
    for req in ex.requirements:
        if req.kind not in ("hard", "soft"):
            continue
        if _present(req, resume_skills, resume_lower):
            out.append(GapItem(req.item, req.kind, req.required, "shown", facts.evidence_for(req.item)))
        elif req.item in pool:
            out.append(GapItem(req.item, req.kind, req.required, "hidden", facts.evidence_for(req.item), "In your skill pool; add it to Skills."))
        else:
            fam = tax.family(req.item)
            related = [s for s in tax.same_family(req.item) if s in pool] if fam and fam not in NO_ADJACENCY_FAMILIES else []
            if related:
                ev = sorted({e for s in related for e in facts.evidence_for(s)})
                out.append(GapItem(req.item, req.kind, req.required, "adjacent", ev, f"Related evidence: {', '.join(related)}. Frame honestly in a cover letter; do not list it as a skill."))
            else:
                out.append(GapItem(req.item, req.kind, req.required, "gap", [], "No evidence. Disclose if asked; learning target."))
    order = {"gap": 0, "adjacent": 1, "hidden": 2, "shown": 3}
    out.sort(key=lambda g: (order[g.status], not g.required, g.item.lower()))
    return out


def _hard_skills(ex: Extraction, resume_skills: set[str], resume_lower: str) -> Component:
    reqs = ex.hard()
    if not reqs:
        return Component("hard_skills", WEIGHTS["hard_skills"], None, "No hard skills found in the JD.")
    total = matched = 0.0
    missing_required: list[str] = []
    for r in reqs:
        w = 2.0 if r.required else 1.0
        total += w
        if _present(r, resume_skills, resume_lower):
            matched += w
        elif r.required:
            missing_required.append(r.item)
    n_req = sum(1 for r in reqs if r.required)
    n_req_hit = n_req - len(missing_required)
    detail = f"{n_req_hit}/{n_req} must-haves, {sum(1 for r in reqs if not r.required and _present(r, resume_skills, resume_lower))}/{len(reqs) - n_req} nice-to-haves on the resume."
    if missing_required:
        detail += f" Missing: {', '.join(missing_required[:8])}."
    return Component("hard_skills", WEIGHTS["hard_skills"], matched / total, detail)


def _keywords(ex: Extraction, resume_text: str) -> Component:
    tax = get_taxonomy()
    jd_counts = dict(ex.keyword_counts)
    for r in ex.requirements:
        if r.kind in ("hard", "soft") and not r.in_taxonomy:
            jd_counts.setdefault(r.item, 1)
    if not jd_counts:
        return Component("keywords", WEIGHTS["keywords"], None, "No keywords found in the JD.")
    resume_counts = tax.find(resume_text)
    lower = resume_text.lower()
    got = want = 0
    for term, n in jd_counts.items():
        w = min(n, KEYWORD_CAP)
        have = resume_counts.get(term) or len(re.findall(rf"(?<!\w){re.escape(term.lower())}(?!\w)", lower))
        want += w
        got += min(have, w)
    return Component("keywords", WEIGHTS["keywords"], got / want, f"Covers {got}/{want} capped keyword mentions ({len(jd_counts)} distinct terms).")


def _clean_title(t: str) -> str:
    t = re.sub(r"[\(\)\[\],/|\-:]+", " ", t)
    t = TITLE_NOISE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def _title_level(ex: Extraction, facts: Facts) -> Component:
    title = _clean_title(ex.title or "")
    targets = facts.profile.target_titles
    if not title or not targets:
        return Component("title_level", WEIGHTS["title_level"], None, "No title to compare.")
    best_t, best = "", 0.0
    jd_tokens = set(title.split())
    for t in targets:
        ct = _clean_title(t)
        ratio = SequenceMatcher(None, title, ct).ratio()
        tt = set(ct.split())
        overlap = len(jd_tokens & tt) / len(tt) if tt else 0
        s = max(ratio, overlap)
        if s > best:
            best, best_t = s, t
    value = best
    notes = [f"closest target title '{best_t}' ({best:.0%})"]
    if ex.seniority == "senior":
        value *= 0.5
        notes.append("senior-level title")
    if ex.min_years is not None and ex.min_years > facts.profile.years_experience:
        gap = ex.min_years - facts.profile.years_experience
        value *= max(0.4, 1 - 0.15 * gap)
        notes.append(f"asks {ex.min_years:g} yrs vs your {facts.profile.years_experience:g}")
    return Component("title_level", WEIGHTS["title_level"], value, "; ".join(notes).capitalize() + ".")


def _education(ex: Extraction, facts: Facts) -> Component:
    lvl = ex.education.get("level")
    if not lvl:
        return Component("education", WEIGHTS["education"], None, "JD does not ask for a degree.")
    mine = facts.profile.degree
    value = 1.0 if EDU_RANK.get(mine.level, 2) >= EDU_RANK[lvl] else 0.0
    fields = ex.education.get("fields") or []
    detail = f"Asks for {lvl}{' (required)' if ex.education.get('required') else ' (preferred)'}; you are completing a {mine.level} in {mine.field or 'your field'}."
    if value and fields:
        my_field = mine.field.lower()
        if not any(f in my_field or my_field in f or f == "engineering" for f in fields):
            value = 0.6
            detail += f" Field asked: {', '.join(fields)}."
    return Component("education", WEIGHTS["education"], value, detail)


def _format(format_score: float | None) -> Component:
    if format_score is None:
        return Component("format", WEIGHTS["format"], 0.8, "Estimated. Upload your PDF in Parse check for a measured value.")
    return Component("format", WEIGHTS["format"], format_score, "From your last PDF parse check.")


def score(ex: Extraction, resume_text: str, jd_text: str, facts: Facts, format_score: float | None = None) -> ScoreResult:
    tax = get_taxonomy()
    resume_skills = set(tax.find(resume_text))
    resume_lower = resume_text.lower()
    sem_value, backend = similarity(resume_text, jd_text)
    components = [
        _hard_skills(ex, resume_skills, resume_lower),
        Component("semantic", WEIGHTS["semantic"], sem_value, f"Resume vs JD similarity ({backend})."),
        _title_level(ex, facts),
        _keywords(ex, resume_text),
        _format(format_score),
        _education(ex, facts),
    ]
    applicable = [c for c in components if c.value is not None]
    weight_sum = sum(c.weight for c in applicable)
    total = 100 * sum(c.weight * c.value for c in applicable) / weight_sum if weight_sum else 0.0
    return ScoreResult(round(total, 1), components, classify_gaps(ex, resume_text, facts), backend)
