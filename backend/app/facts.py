"""Facts file: your evidenced skills, locked resume text and eligibility facts.

Everything the tailor may say must be traceable to this file. The validator checks drafts
against it, so keep it honest: a skill goes in `skill_pool` only when a project, role or
certification proves it.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings, resolve_data_file
from app.engine.skills import get_taxonomy


class Contact(BaseModel):
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    github: str | None = None
    location: str | None = None


class Degree(BaseModel):
    level: str = "bachelor"  # diploma | associate | bachelor | master | phd
    field: str = ""
    institution: str = ""


class Profile(BaseModel):
    name: str
    contact: Contact = Contact()
    graduation: date  # expected graduation, e.g. 2027-05-01
    degree: Degree = Degree()
    current_location: str = ""
    open_to_regions: list[str] = Field(default_factory=list)
    # Region key -> True when you would need visa sponsorship to work there.
    needs_sponsorship: dict[str, bool] = Field(default_factory=dict)
    languages: list[str] = Field(default_factory=lambda: ["English"])
    years_experience: float = 0.0
    target_titles: list[str] = Field(default_factory=list)
    # Longest internship / co-op term you can take, in months (None = no limit).
    max_term_months: int | None = None
    earliest_start: date | None = None

    @field_validator("graduation", "earliest_start", mode="before")
    @classmethod
    def _month_to_date(cls, v):
        if isinstance(v, str) and len(v) == 7:
            return f"{v}-01"
        return v


class PoolSkill(BaseModel):
    skill: str
    evidence: list[str] = Field(default_factory=list)


class LockedEntry(BaseModel):
    title: str
    org: str | None = None
    dates: str | None = None
    tech: str | None = None
    bullets: list[str] = Field(default_factory=list)


class Resume(BaseModel):
    section_order: list[str]
    objective_template: str
    objective: str
    # Ordered skills lines: label -> items. Only items from skill_pool are allowed.
    skills: dict[str, list[str]]
    skills_line_max_chars: int = 110
    projects: list[LockedEntry] = Field(default_factory=list)
    experience: list[LockedEntry] = Field(default_factory=list)
    education: list[LockedEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class Facts(BaseModel):
    profile: Profile
    skill_pool: list[PoolSkill]
    resume: Resume
    banned_phrases: list[str] = Field(default_factory=list)

    def pool_names(self) -> set[str]:
        """Canonical names of every evidenced skill."""
        tax = get_taxonomy()
        return {tax.canonical(s.skill) or s.skill for s in self.skill_pool}

    def evidence_for(self, skill: str) -> list[str]:
        tax = get_taxonomy()
        for s in self.skill_pool:
            if (tax.canonical(s.skill) or s.skill) == skill:
                return s.evidence
        return []


def load_facts(path: Path | None = None) -> Facts:
    path = path or resolve_data_file(get_settings().facts_path)
    return Facts.model_validate(yaml.safe_load(path.read_text()))


@lru_cache
def get_facts() -> Facts:
    return load_facts()


def render_resume_text(facts: Facts, objective: str | None = None, skills: dict[str, list[str]] | None = None) -> str:
    """Plain-text resume in section order, the way a basic ATS text extractor would see it."""
    r = facts.resume
    p = facts.profile
    objective = objective if objective is not None else r.objective
    skills = skills if skills is not None else r.skills
    blocks: dict[str, str] = {}

    contact = " | ".join(x for x in [p.contact.email, p.contact.phone, p.contact.linkedin, p.contact.github, p.contact.location] if x)
    blocks["header"] = f"{p.name}\n{contact}".strip()
    blocks["objective"] = f"OBJECTIVE\n{objective}"
    blocks["skills"] = "SKILLS\n" + "\n".join(f"{label}: {', '.join(items)}" for label, items in skills.items())

    def entries(head: str, items: list[LockedEntry]) -> str:
        out = [head]
        for e in items:
            line = " | ".join(x for x in [e.title, e.org, e.tech, e.dates] if x)
            out.append(line)
            out.extend(f"- {b}" for b in e.bullets)
        return "\n".join(out)

    blocks["projects"] = entries("PROJECTS", r.projects)
    blocks["experience"] = entries("EXPERIENCE", r.experience)
    blocks["education"] = entries("EDUCATION", r.education)
    blocks["certifications"] = "CERTIFICATIONS\n" + "\n".join(r.certifications)

    return "\n\n".join(blocks[s.lower()] for s in r.section_order if s.lower() in blocks)
