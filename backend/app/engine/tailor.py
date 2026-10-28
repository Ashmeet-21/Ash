"""Tailor: rewrites only the Objective and Skills for one job, then validates.

The template tailor is deterministic and always available. When Claude is configured,
Claude Sonnet fills the Objective's slots instead (better phrasing of the role and skill
areas); every draft goes through the validator and a failing draft is sent back with the
errors, up to `max_redrafts` times, before falling back to the template result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import get_settings
from app.engine.extract import Extraction
from app.engine.scorer import TITLE_NOISE
from app.engine.skills import get_taxonomy
from app.engine.validator import ValidationResult, validate_tailored
from app.facts import Facts
from app.llm import structured_call

# Skill family -> plain-language area phrase used in the Objective.
AREA_BY_FAMILY = {
    "siem": "security monitoring",
    "secops": "incident response",
    "frameworks-sec": "threat detection",
    "appsec": "application security",
    "offsec": "offensive security",
    "vulnmgmt": "vulnerability management",
    "netsec": "networking",
    "cloudsec": "cloud security",
    "identity": "identity management",
    "py-web": "backend APIs",
    "js-backend": "backend APIs",
    "jvm-web": "backend APIs",
    "api": "backend APIs",
    "js-frontend": "full stack web apps",
    "data-sql": "relational databases",
    "containers": "containerized deployment",
    "cicd": "CI/CD automation",
    "cloud": "cloud infrastructure",
    "llm": "LLM tooling",
    "llm-api": "LLM tooling",
    "ml": "machine learning",
    "ml-framework": "machine learning",
    "data-py": "data analysis",
    "data-analysis": "data analysis",
    "scripting": "automation scripting",
    "testing": "automated testing",
}
EXCLUDED_TOOL_FAMILIES = {"soft", "certs", "cs-fundamentals", "process"}
# Broad practices rather than tools; they read wrong in "using X, Y and Z".
NOT_TOOLS = {
    "SOC operations", "Incident response", "Threat hunting", "Threat intelligence", "Log analysis", "Networking",
    "Network security", "Application security", "Cloud security", "Penetration testing", "Vulnerability management",
    "Threat modeling", "Phishing analysis", "Malware analysis", "Digital forensics", "Machine learning", "Deep learning",
    "NLP", "LLMs", "Prompt engineering", "AI agents", "Data analysis", "Data visualization", "Microservices",
    "System design", "Unit testing", "CI/CD", "REST APIs", "Embeddings", "RAG", "MLOps", "ETL",
}


@dataclass
class TailorResult:
    objective: str
    skills: dict[str, list[str]]
    role: str
    areas: list[str]
    tools: list[str]
    validation: ValidationResult
    source: str  # template | claude
    attempts: list[dict] = field(default_factory=list)


def _importance(ex: Extraction) -> dict[str, float]:
    """How much the JD weights each skill: must-haves 2x, plus mentions."""
    imp: dict[str, float] = {}
    for r in ex.requirements:
        if r.kind in ("hard", "soft"):
            imp[r.item] = (2.0 if r.required else 1.0) + 0.25 * min(r.mentions, 4)
    return imp


GENERIC_ROLES = {"engineer", "developer", "programmer", "architect"}


def clean_role(title: str, facts: Facts | None = None) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", title)
    t = re.split(r"\s[-|/,:]\s|,", t)[0]
    if facts is not None:
        # Drop skills you can't evidence so the role never implies them. Before the noise
        # filter, which would eat the "Spring" in "Spring Boot" as a season.
        t = get_taxonomy().remove(t, set(facts.pool_names()))
    t = TITLE_NOISE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" -,")
    if t.lower() in GENERIC_ROLES:
        t = f"Software {t}"  # "Java Engineer" -> "Engineer" -> "Software Engineer"
    return t or "entry-level"


def join_list(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def fill_template(template: str, role: str, areas: list[str], tools: list[str]) -> str:
    text = " ".join(template.split())
    # Keep the article right: "a {role}" -> "an AI Engineer".
    if re.match(r"[AEIOU]|iOS\b|SRE\b|ML\b|MLOps\b|LLM\b|NLP\b", role):
        text = re.sub(r"\ba \{role\}", "an {role}", text)
    return text.replace("{role}", role).replace("{areas}", join_list(areas)).replace("{tools}", join_list(tools))


def pick_tools(ex: Extraction, facts: Facts, n_min: int = 8, n_max: int = 10) -> list[str]:
    tax = get_taxonomy()
    pool = facts.pool_names()
    imp = _importance(ex)
    usable = [s for s in pool if tax.family(s) not in EXCLUDED_TOOL_FAMILIES and tax.kind(s) != "soft" and s not in NOT_TOOLS]
    matched = sorted((s for s in usable if s in imp), key=lambda s: -imp[s])
    tools = matched[:n_max]
    if len(tools) < n_min:
        # Fill with tools from the master objective, then the master Skills order.
        master_order = list(tax.find(facts.resume.objective)) + [i for items in facts.resume.skills.values() for i in items]
        for s in master_order:
            canon = tax.canonical(s) or s
            if canon in usable and canon not in tools:
                tools.append(canon)
            if len(tools) >= n_min:
                break
    return tools


def pick_areas(ex: Extraction, facts: Facts, n_max: int = 3) -> list[str]:
    tax = get_taxonomy()
    pool = facts.pool_names()
    imp = _importance(ex)
    score: dict[str, float] = {}
    for s in pool:
        area = AREA_BY_FAMILY.get(tax.family(s) or "")
        if area:
            score[area] = score.get(area, 0) + imp.get(s, 0)
    ranked = [a for a, v in sorted(score.items(), key=lambda kv: -kv[1]) if v > 0]
    if len(ranked) < 2:
        # Fall back to areas evidenced by the master objective.
        for a in sorted(score, key=lambda a: -score[a]):
            if a not in ranked:
                ranked.append(a)
            if len(ranked) >= 2:
                break
    # Drop near-duplicates ("security monitoring" vs "security monitoring and incident response").
    out: list[str] = []
    for a in ranked:
        if any(a in b or b in a for b in out):
            continue
        if any(name not in pool for name in tax.find(a)):
            continue  # the phrase itself would claim a skill you lack
        out.append(a)
    return out[:n_max]


def tailor_skills(ex: Extraction, facts: Facts) -> dict[str, list[str]]:
    """Reorder Skills lines so JD-matched skills lead; pull in hidden pool skills; cap line length."""
    tax = get_taxonomy()
    pool = facts.pool_names()
    imp = _importance(ex)
    lines = {label: [tax.canonical(i) or i for i in items] for label, items in facts.resume.skills.items()}
    shown = {i for items in lines.values() for i in items}

    # Hidden skills the JD wants go to the line whose items share their family.
    for s in sorted((s for s in pool if s in imp and s not in shown and tax.kind(s) != "soft" and tax.family(s) != "certs"), key=lambda s: -imp[s]):
        fam = tax.family(s)
        best = max(lines, key=lambda lbl: sum(1 for i in lines[lbl] if tax.family(i) == fam))
        if not any(tax.family(i) == fam for i in lines[best]):
            best = list(lines)[-1]
        lines[best].append(s)

    limit = facts.resume.skills_line_max_chars
    out: dict[str, list[str]] = {}
    for label, items in lines.items():
        ordered = sorted(items, key=lambda i: (-imp.get(i, 0), items.index(i)))
        # Trim least relevant items until the line fits.
        while len(f"{label}: {', '.join(ordered)}") > limit and len(ordered) > 1:
            ordered.pop()
        out[label] = ordered
    return out


DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "role": {"type": "string"},
        "areas": {"type": "array", "items": {"type": "string"}},
        "tools": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["role", "areas", "tools"],
    "additionalProperties": False,
}

DRAFT_SYSTEM = """You fill three slots in a student's fixed resume Objective template for one job posting.

Slots:
- role: the job's role name as a hiring manager would say it, without seniority, location or term words. If the title names a technology not on the ALLOWED SKILLS list, drop it ("Java Developer" becomes "Software Developer").
- areas: 2 or 3 short skill-area phrases (2 to 5 words each, lowercase) that this job weights most AND that the student's evidence supports.
- tools: 8 to 10 tools or skills, most relevant to this job first.

Hard rules:
- Every tool must be copied exactly from the ALLOWED SKILLS list. Never name anything not on that list, even if the job asks for it.
- Areas must describe work the listed evidence proves. Do not name specific technologies in areas.
- Never overclaim: no "production experience", "expert", "senior", "years of experience" or similar.
- Each area is one phrase without commas or the word "and".
- Do not use em dashes."""


def _draft_with_claude(ex: Extraction, jd_text: str, facts: Facts, feedback: list[str]) -> dict | None:
    allowed = sorted(
        (s.skill for s in facts.skill_pool if (get_taxonomy().canonical(s.skill) or s.skill) not in NOT_TOOLS and get_taxonomy().family(get_taxonomy().canonical(s.skill) or "") not in EXCLUDED_TOOL_FAMILIES),
        key=str.lower,
    )
    evidence = "\n".join(f"- {s.skill}: {', '.join(s.evidence)}" for s in facts.skill_pool)
    prompt = (
        f"TEMPLATE:\n{facts.resume.objective_template}\n\n"
        f"ALLOWED SKILLS (copy exactly):\n{', '.join(allowed)}\n\n"
        f"EVIDENCE:\n{evidence}\n\n"
        f"JOB TITLE: {ex.title}\n\n<job_description>\n{jd_text[:20000]}\n</job_description>"
    )
    if feedback:
        prompt += "\n\nYour previous draft was rejected by the validator:\n" + "\n".join(f"- {f}" for f in feedback) + "\nFix every issue."
    return structured_call(model=get_settings().draft_model, system=DRAFT_SYSTEM, prompt=prompt, schema=DRAFT_SCHEMA, max_tokens=2000, effort="medium")


def tailor(ex: Extraction, jd_text: str, facts: Facts, use_llm: bool = True) -> TailorResult:
    skills = tailor_skills(ex, facts)
    attempts: list[dict] = []

    if use_llm:
        feedback: list[str] = []
        for _ in range(get_settings().max_redrafts):
            draft = _draft_with_claude(ex, jd_text, facts, feedback)
            if draft is None:
                break
            tax = get_taxonomy()
            tools = [tax.canonical(t) or t for t in draft["tools"]]
            role = draft["role"].strip()
            objective = fill_template(facts.resume.objective_template, role, draft["areas"], tools)
            validation = validate_tailored(objective, skills, facts)
            attempts.append({"objective": objective, "validation": validation.to_dict()})
            if validation.ok:
                return TailorResult(objective, skills, role, draft["areas"], tools, validation, "claude", attempts)
            feedback = [i.message for i in validation.errors]

    role = clean_role(ex.title, facts)
    areas = pick_areas(ex, facts)
    tools = pick_tools(ex, facts)
    objective = fill_template(facts.resume.objective_template, role, areas, tools)
    validation = validate_tailored(objective, skills, facts)
    return TailorResult(objective, skills, role, areas, tools, validation, "template", attempts)
