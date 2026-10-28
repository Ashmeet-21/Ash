"""Deterministic rule validator: the pre-delivery checklist, in code.

The LLM drafts; this decides. A draft that fails any error-level rule is rejected.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.engine.skills import get_taxonomy
from app.facts import Facts, render_resume_text

EM_DASHES = re.compile("[—―⸺⸻]")
GPA = re.compile(r"\b(c\.?\s?gpa|gpa|grade point average)\b", re.I)
LEARNING_TAG = re.compile(r"\(\s*learning\s*\)", re.I)
SLOTS = ("role", "areas", "tools")


@dataclass
class Issue:
    rule: str
    message: str


@dataclass
class ValidationResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": [asdict(i) for i in self.errors], "warnings": [asdict(i) for i in self.warnings]}

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        self.errors += other.errors
        self.warnings += other.warnings
        return self


def template_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"\{(role|areas|tools)\}", " ".join(template.split()))
    pattern = ""
    for i, part in enumerate(parts):
        if i % 2:
            pattern += f"(?P<{part}>.+?)"
            continue
        a_before_role = i + 1 < len(parts) and parts[i + 1] == "role" and re.search(r"(^|\s)a $", part)
        if a_before_role:
            part = part[:-2]
        pattern += re.escape(part).replace(r"\ ", r"\s+")
        if a_before_role:
            pattern += r"an?\s+"
    return re.compile(rf"^{pattern}$", re.S)


def split_list(s: str) -> list[str]:
    return [x.strip() for x in re.split(r",\s*|\s+and\s+", s.strip().rstrip(".")) if x.strip()]


def validate_objective(objective: str, facts: Facts) -> ValidationResult:
    res = ValidationResult()
    tax = get_taxonomy()
    pool = facts.pool_names()

    m = template_regex(facts.resume.objective_template).match(" ".join(objective.split()))
    if not m:
        res.errors.append(Issue("objective_template", "Objective does not follow your fixed template."))
    else:
        tools = split_list(m.group("tools"))
        areas = split_list(m.group("areas"))
        if not 8 <= len(tools) <= 10:
            res.warnings.append(Issue("objective_tools_count", f"Objective names {len(tools)} tools; target is 8 to 10."))
        if not 2 <= len(areas) <= 3:
            res.warnings.append(Issue("objective_areas_count", f"Objective names {len(areas)} skill areas; target is 2 to 3."))
        for t in tools:
            canon = tax.canonical(t)
            if (canon or t) not in pool:
                res.errors.append(Issue("objective_unlisted_skill", f"Tool '{t}' is not in your evidenced skill pool."))

    # The role is checked on its own: "seeking a Java Engineer role" reads as a Java claim to a recruiter.
    claims = objective
    if m:
        claims = objective.replace(m.group("role"), " ", 1)
        for name in tax.find(m.group("role")):
            if name not in pool:
                res.errors.append(Issue("objective_role_skill", f"Role '{m.group('role')}' names '{name}', which is not in your skill pool."))
    for name in tax.find(claims):
        if name not in pool:
            res.errors.append(Issue("objective_unlisted_skill", f"Objective names '{name}', which is not in your skill pool."))
    for phrase in facts.banned_phrases:
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", objective, re.I):
            res.errors.append(Issue("overclaim", f"Objective contains banned phrase '{phrase}'."))
    return res


def validate_skills(skills: dict[str, list[str]], facts: Facts) -> ValidationResult:
    res = ValidationResult()
    tax = get_taxonomy()
    pool = facts.pool_names()
    master_labels = list(facts.resume.skills.keys())
    if list(skills.keys()) != master_labels:
        res.errors.append(Issue("skills_labels", f"Skills lines must stay {master_labels}."))
    seen: set[str] = set()
    for label, items in skills.items():
        line = f"{label}: {', '.join(items)}"
        if len(line) > facts.resume.skills_line_max_chars:
            res.errors.append(Issue("skills_line_length", f"'{label}' line is {len(line)} chars; limit {facts.resume.skills_line_max_chars}."))
        for item in items:
            canon = tax.canonical(item) or item
            if canon not in pool:
                res.errors.append(Issue("skills_unlisted", f"'{item}' is not in your evidenced skill pool."))
            if canon in seen:
                res.errors.append(Issue("skills_duplicate", f"'{item}' appears twice."))
            seen.add(canon)
    return res


def validate_text_rules(text: str) -> ValidationResult:
    res = ValidationResult()
    if EM_DASHES.search(text):
        res.errors.append(Issue("em_dash", f"Found {len(EM_DASHES.findall(text))} em dash(es)."))
    if GPA.search(text):
        res.errors.append(Issue("no_cgpa", "CGPA/GPA must not appear."))
    if LEARNING_TAG.search(text):
        res.errors.append(Issue("no_learning_tag", "'(learning)' tags are not allowed."))
    return res


def _norm(s: str) -> str:
    return " ".join(s.split())


def validate_document(text: str, facts: Facts) -> ValidationResult:
    """Check the final extracted document text: order, locked text byte-identical, formatting rules."""
    res = validate_text_rules(text)
    flat = _norm(text)
    r = facts.resume

    # Section order.
    heading_pos = []
    for section in r.section_order:
        if section.lower() == "header":
            continue
        m = re.search(rf"(?m)^\s*{re.escape(section.upper())}\s*$", text)
        if not m:
            res.errors.append(Issue("section_missing", f"Section '{section}' not found."))
        else:
            heading_pos.append((m.start(), section))
    if [s for _, s in sorted(heading_pos)] != [s for _, s in heading_pos]:
        res.errors.append(Issue("section_order", "Sections are out of order."))

    # Locked entries: titles in fixed order, bullets word-for-word.
    for group_name, group in (("projects", r.projects), ("experience", r.experience), ("education", r.education)):
        last = -1
        for e in group:
            pos = flat.find(_norm(e.title))
            if pos < 0:
                res.errors.append(Issue("locked_title", f"{group_name} title '{e.title}' missing or altered."))
                continue
            if pos < last:
                res.errors.append(Issue("project_order", f"'{e.title}' is out of order in {group_name}."))
            last = pos
            for b in e.bullets:
                if _norm(b) not in flat:
                    res.errors.append(Issue("locked_bullet", f"Locked bullet changed or missing: '{b[:70]}...'"))

    # Title/date collision: the same title twice, or two entries sharing exact dates and title.
    titles = [e.title for e in [*r.projects, *r.experience]]
    for t in {t for t in titles if titles.count(t) > 1}:
        res.errors.append(Issue("title_collision", f"Title '{t}' appears more than once."))
    keys = [(e.title.lower(), (e.dates or "").lower()) for e in [*r.projects, *r.experience] if e.dates]
    if len(keys) != len(set(keys)):
        res.errors.append(Issue("date_collision", "Two entries share the same title and dates."))
    return res


def validate_tailored(objective: str, skills: dict[str, list[str]], facts: Facts) -> ValidationResult:
    res = validate_objective(objective, facts)
    res.merge(validate_skills(skills, facts))
    res.merge(validate_document(render_resume_text(facts, objective, skills), facts))
    return res
