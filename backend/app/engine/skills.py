"""Skill taxonomy and matcher: turns free text into canonical skill names.

Matching is deterministic and explainable. Every alias is matched on word boundaries so
"Java" never matches inside "JavaScript" and "SQL" never matches inside "PostgreSQL".
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import DATA_DIR

SKILLS_PATH = DATA_DIR / "skills.yaml"


@dataclass(frozen=True)
class Skill:
    name: str
    family: str
    kind: str = "hard"
    aliases: tuple[str, ...] = ()
    cs_aliases: tuple[str, ...] = ()
    strict: bool = False


@dataclass
class Taxonomy:
    skills: dict[str, Skill]
    _patterns: list[tuple[re.Pattern[str], str]] = field(default_factory=list)
    _lookup: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for skill in self.skills.values():
            terms = [] if skill.strict else [skill.name, *skill.aliases]
            if skill.strict:
                terms = list(skill.aliases)
            for term in terms:
                self._lookup[_norm(term)] = skill.name
                self._patterns.append((_compile(term, case_sensitive=False), skill.name))
            for term in skill.cs_aliases:
                self._patterns.append((_compile(term, case_sensitive=True), skill.name))
            self._lookup[_norm(skill.name)] = skill.name
        # Longest terms first so "React Native" claims its span before "React".
        self._patterns.sort(key=lambda p: -len(p[0].pattern))

    def canonical(self, term: str) -> str | None:
        """Map a single term (e.g. 'k8s') to its canonical name, or None if unknown."""
        hit = self._lookup.get(_norm(term))
        if hit:
            return hit
        found = self.find(term)
        if len(found) == 1:
            return next(iter(found))
        return None

    def find(self, text: str) -> Counter[str]:
        """Count canonical skills mentioned in `text`. Overlapping spans are claimed once."""
        counts: Counter[str] = Counter()
        taken: list[tuple[int, int]] = []
        for pattern, name in self._patterns:
            for m in pattern.finditer(text):
                span = m.span()
                if any(span[0] < e and s < span[1] for s, e in taken):
                    continue
                taken.append(span)
                counts[name] += 1
        return counts

    def family(self, name: str) -> str | None:
        skill = self.skills.get(name)
        return skill.family if skill else None

    def kind(self, name: str) -> str:
        skill = self.skills.get(name)
        return skill.kind if skill else "hard"

    def same_family(self, name: str) -> list[str]:
        fam = self.family(name)
        return [s.name for s in self.skills.values() if fam and s.family == fam and s.name != name]


def _norm(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip().lower())


def _compile(term: str, case_sensitive: bool) -> re.Pattern[str]:
    escaped = re.escape(term.strip()).replace(r"\ ", r"[\s\-]+")
    # Custom boundaries: a skill may start/end with symbols (C++, .NET, C#), so plain \b is not enough.
    pattern = rf"(?<![\w+#.])(?:{escaped})(?![\w+#]|\.\w)"
    return re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)


def load_taxonomy(path: Path = SKILLS_PATH) -> Taxonomy:
    raw = yaml.safe_load(path.read_text())
    skills: dict[str, Skill] = {}
    for item in raw["skills"]:
        skills[item["name"]] = Skill(
            name=item["name"],
            family=item.get("family", "other"),
            kind=item.get("kind", "hard"),
            aliases=tuple(item.get("aliases", []) or []),
            cs_aliases=tuple(item.get("cs_aliases", []) or []),
            strict=bool(item.get("strict", False)),
        )
    return Taxonomy(skills)


@lru_cache
def get_taxonomy() -> Taxonomy:
    return load_taxonomy()
