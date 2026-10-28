"""Orchestration: ties the engine to the database. Routes stay thin and call into here."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings, resolve_data_file
from app.engine.document import build_and_check
from app.engine.eligibility import check_all
from app.engine.extract import Extraction, extract, jd_hash
from app.engine.scorer import score
from app.engine.skills import get_taxonomy
from app.engine.tailor import tailor
from app.facts import Facts, get_facts, render_resume_text
from app.llm import llm_available
from app.models import Application, Flag, Job, JobRequirement, MatchScore, ProfileFact, ResumeVersion, utcnow
from app.regions import get_regions
from app.sources.adzuna import adzuna
from app.sources.ats import FETCHERS
from app.sources.base import JobIn, SourceError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- profile

def sync_profile_facts(db: Session, facts: Facts) -> None:
    """Mirror the facts file's skill pool into profile_facts."""
    tax = get_taxonomy()
    db.query(ProfileFact).delete()
    for s in facts.skill_pool:
        canon = tax.canonical(s.skill) or s.skill
        skill = tax.skills.get(canon)
        db.add(ProfileFact(skill=canon, evidence=s.evidence, aliases=list(skill.aliases) if skill else [], locked=False))
    db.commit()


def ensure_master(db: Session, facts: Facts | None = None) -> ResumeVersion:
    """The master resume version matching the current facts file (created when the file changes)."""
    facts = facts or get_facts()
    rows = db.scalars(
        select(ResumeVersion).where(ResumeVersion.parent_id.is_(None), ResumeVersion.job_id.is_(None)).order_by(ResumeVersion.id.desc())
    ).all()
    for row in rows:
        if row.objective == facts.resume.objective and row.skills_line == facts.resume.skills:
            return row
    prev = rows[0] if rows else None
    master = ResumeVersion(
        objective=facts.resume.objective,
        skills_line=facts.resume.skills,
        # Keep the last parse check: the layout usually doesn't change with the text.
        validation={"parse_check": (prev.validation or {}).get("parse_check")} if prev and prev.validation else None,
    )
    db.add(master)
    db.commit()
    return master


def format_score(db: Session) -> float | None:
    pc = (ensure_master(db).validation or {}).get("parse_check")
    return pc.get("format_score") if pc else None


def save_parse_check(db: Session, result: dict) -> None:
    master = ensure_master(db)
    master.validation = {**(master.validation or {}), "parse_check": {k: v for k, v in result.items() if k != "text"}}
    db.commit()


# ---------------------------------------------------------------- scoring

def get_extraction(db: Session, job: Job, use_llm: bool = True) -> Extraction:
    """Extraction cached per JD hash, so re-scoring never pays for Claude twice."""
    h = jd_hash(job.jd_text)
    cache = job.extraction_cache or {}
    if cache.get("hash") == h and (not use_llm or "claude" in cache["data"]["sources"] or not llm_available()):
        return Extraction.from_dict(cache["data"])
    ex = extract(job.jd_text, title=job.title, company=job.company, location=job.location, use_llm=use_llm)
    ex.remote = ex.remote or job.remote
    if job.salary_min and not ex.salary:
        ex.salary = {"min": job.salary_min, "max": job.salary_max, "currency": job.salary_currency}
    job.extraction_cache = {"hash": h, "data": ex.to_dict()}
    return ex


def analyze_job(db: Session, job: Job, use_llm: bool = True) -> MatchScore:
    facts = get_facts()
    ex = get_extraction(db, job, use_llm)
    master = ensure_master(db, facts)
    # Pasted JDs often carry these only in the text; keep the row filterable.
    job.title = job.title or ex.title or "Untitled role"
    job.company = job.company or ex.company
    job.location = job.location or ex.location
    job.remote = job.remote or ex.remote
    if ex.salary and not job.salary_min:
        job.salary_min, job.salary_max, job.salary_currency = ex.salary["min"], ex.salary["max"], ex.salary["currency"]

    job.requirements.clear()
    for r in ex.requirements:
        job.requirements.append(JobRequirement(item=r.item, kind=r.kind, required=r.required))
    job.flags.clear()
    for f in check_all(job.jd_text, ex, facts):
        job.flags.append(Flag(type=f.type, severity=f.severity, evidence_text=f"{f.message}\n{f.evidence}".strip()))

    fmt = format_score(db)
    result = score(ex, render_resume_text(facts), job.jd_text, facts, fmt)
    breakdown = result.breakdown()
    breakdown["_meta"] = {"potential": potential_score(ex, job.jd_text, facts, fmt)}
    db.query(MatchScore).filter(MatchScore.job_id == job.id, MatchScore.resume_version_id == master.id).delete()
    ms = MatchScore(job_id=job.id, resume_version_id=master.id, total=result.total, breakdown=breakdown, gaps=result.gaps_dict())
    db.add(ms)
    db.commit()
    return ms


def potential_score(ex: Extraction, jd_text: str, facts: Facts, fmt: float | None) -> float:
    """Score after the deterministic tailor: what this job is worth once Objective and Skills are fitted."""
    t = tailor(ex, jd_text, facts, use_llm=False)
    if not t.validation.ok:
        return score(ex, render_resume_text(facts), jd_text, facts, fmt).total
    return score(ex, render_resume_text(facts, t.objective, t.skills), jd_text, facts, fmt).total


def job_hash(company: str | None, title: str, location: str | None) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return hashlib.sha256(f"{norm(company)}|{norm(title)}|{norm(location)}".encode()).hexdigest()


def upsert_job(db: Session, j: JobIn) -> tuple[Job, str]:
    """Insert or refresh a posting. Returns (job, status) with status new | updated | unchanged | duplicate."""
    now = utcnow()
    h = job_hash(j.company, j.title, j.location)
    job = db.scalar(select(Job).where(Job.source == j.source, Job.external_id == j.external_id))
    if job:
        job.last_seen_at, job.active = now, True
        if job.jd_text != j.jd_text or job.title != j.title:
            job.jd_text, job.title, job.location, job.hash = j.jd_text, j.title, j.location, h
            return job, "updated"
        return job, "unchanged"
    dup = db.scalar(select(Job).where(Job.hash == h, Job.active.is_(True)))
    if dup:
        dup.last_seen_at = now
        # Prefer the richer description when the same role shows up from two sources.
        if len(j.jd_text) > len(dup.jd_text) * 1.3:
            dup.jd_text = j.jd_text
            return dup, "updated"
        return dup, "duplicate"
    job = Job(
        source=j.source, external_id=j.external_id, company=j.company, title=j.title, location=j.location,
        remote=j.remote, posted_at=j.posted_at, jd_text=j.jd_text, url=j.url, hash=h,
        salary_min=j.salary_min, salary_max=j.salary_max, salary_currency=j.salary_currency,
        first_seen_at=now, last_seen_at=now,
    )
    db.add(job)
    db.flush()
    return job, "new"


def score_posting(db: Session, j: JobIn, use_llm: bool = True) -> Job:
    job, _ = upsert_job(db, j)
    db.commit()
    analyze_job(db, job, use_llm)
    return job


# ---------------------------------------------------------------- ingest

def load_watchlist() -> dict:
    return yaml.safe_load(resolve_data_file(get_settings().watchlist_path).read_text()) or {}


def _title_ok(title: str, wl: dict) -> bool:
    t = title.lower()
    inc = [x.lower() for x in wl.get("title_include") or []]
    exc = [x.lower() for x in wl.get("title_exclude") or []]
    if any(re.search(rf"(?<!\w){re.escape(x)}(?!\w)", t) for x in exc):
        return False
    return not inc or any(re.search(rf"(?<!\w){re.escape(x)}(?!\w)", t) for x in inc)


def ingest(db: Session, use_llm: bool = True) -> dict:
    wl = load_watchlist()
    summary = {"fetched": 0, "kept": 0, "new": 0, "updated": 0, "duplicates": 0, "closed": 0, "errors": [], "new_matches": []}
    touched: list[Job] = []
    started = utcnow()

    batches: list[tuple[str, list[JobIn], tuple[str, str] | None]] = []
    for c in wl.get("companies") or []:
        fetch = FETCHERS.get(c.get("ats"))
        if not fetch:
            summary["errors"].append(f"{c.get('name')}: unknown ats '{c.get('ats')}'")
            continue
        try:
            batches.append((c["name"], fetch(c["board"], c["name"]), (c["ats"], c["board"])))
        except SourceError as e:
            summary["errors"].append(f"{c['name']}: {e}")
    for s in wl.get("searches") or []:
        try:
            if s.get("source") == "adzuna":
                batches.append((f"adzuna:{s['what']}", adzuna(s["region"], s["what"]), None))
        except SourceError as e:
            summary["errors"].append(f"adzuna '{s.get('what')}': {e}")

    for _, postings, board in batches:
        summary["fetched"] += len(postings)
        for p in postings:
            if not _title_ok(p.title, wl):
                continue
            summary["kept"] += 1
            job, status = upsert_job(db, p)
            if status in ("new", "updated"):
                summary["new" if status == "new" else "updated"] += 1
                touched.append(job)
            elif status == "duplicate":
                summary["duplicates"] += 1
        db.commit()
        # A posting missing from a successful board fetch has closed.
        if board:
            ats_name, board_token = board
            stale = db.scalars(select(Job).where(Job.source == ats_name, Job.external_id.like(f"{board_token}:%"), Job.active.is_(True), Job.last_seen_at < started)).all()
            for job in stale:
                job.active = False
            summary["closed"] += len(stale)
            db.commit()

    threshold = get_settings().alert_min_score
    for job in touched:
        try:
            ms = analyze_job(db, job, use_llm)
        except Exception as e:  # one bad posting must not stop the run
            log.exception("analyze failed for job %s", job.id)
            summary["errors"].append(f"job {job.id}: {e}")
            continue
        blocked = any(f.severity == "block" for f in job.flags)
        potential = (ms.breakdown.get("_meta") or {}).get("potential", ms.total)
        if potential >= threshold and not blocked:
            summary["new_matches"].append({"id": job.id, "title": job.title, "company": job.company, "score": ms.total, "potential": potential})
    summary["new_matches"].sort(key=lambda m: -m["potential"])
    return summary


# ---------------------------------------------------------------- reads

def latest_score(db: Session, job_id: int, version_id: int | None = None) -> MatchScore | None:
    q = select(MatchScore).where(MatchScore.job_id == job_id)
    if version_id:
        q = q.where(MatchScore.resume_version_id == version_id)
    return db.scalar(q.order_by(MatchScore.id.desc()).limit(1))


def role_type(title: str) -> str:
    t = title.lower()
    if re.search(r"\b(co-?op|intern(ship)?|placement|work term)\b", t):
        return "co-op"
    if re.search(r"\b(new grad|graduate|entry[- ]level|early career|junior|jr\.?|associate|fresher)\b", t):
        return "new-grad"
    return "other"


def job_summary(db: Session, job: Job, master_id: int) -> dict:
    ms = latest_score(db, job.id, master_id) or latest_score(db, job.id)
    regions = get_regions().match(f"{job.location or ''} {job.title}")
    if job.remote:
        regions = sorted(set(regions) | {"remote"})
    flags = {"block": 0, "warn": 0, "info": 0}
    for f in job.flags:
        flags[f.severity] += 1
    app_row = db.scalar(select(Application).where(Application.job_id == job.id))
    return {
        "id": job.id, "title": job.title, "company": job.company, "location": job.location, "remote": job.remote,
        "source": job.source, "url": job.url, "posted_at": job.posted_at, "first_seen_at": job.first_seen_at,
        "active": job.active, "regions": regions, "role_type": role_type(job.title),
        "salary": {"min": job.salary_min, "max": job.salary_max, "currency": job.salary_currency} if job.salary_min else None,
        "score": ms.total if ms else None,
        "potential": ((ms.breakdown or {}).get("_meta") or {}).get("potential") if ms else None,
        "flag_counts": flags,
        "application_status": app_row.status if app_row else None,
    }


def job_detail(db: Session, job: Job) -> dict:
    master = ensure_master(db)
    ms = latest_score(db, job.id, master.id) or latest_score(db, job.id)
    ex = (job.extraction_cache or {}).get("data") or {}
    versions = db.scalars(select(ResumeVersion).where(ResumeVersion.job_id == job.id).order_by(ResumeVersion.id.desc())).all()
    d = job_summary(db, job, master.id)
    d.update({
        "jd_text": job.jd_text,
        "extraction": {k: ex.get(k) for k in ("seniority", "min_years", "education", "salary", "sources")},
        "requirements": [{"item": r.item, "kind": r.kind, "required": r.required} for r in job.requirements],
        "breakdown": ms.breakdown if ms else None,
        "gaps": ms.gaps if ms else None,
        "flags": [{"type": f.type, "severity": f.severity, "message": f.evidence_text.split("\n", 1)[0], "evidence": (f.evidence_text.split("\n", 1) + [""])[1]} for f in job.flags],
        "tailored_versions": [version_dict(db, v) for v in versions],
        "snippet_only": job.source == "adzuna",
    })
    return d


def version_dict(db: Session, v: ResumeVersion) -> dict:
    after = latest_score(db, v.job_id, v.id) if v.job_id else None
    return {
        "id": v.id, "job_id": v.job_id, "parent_id": v.parent_id, "objective": v.objective, "skills": v.skills_line,
        "validation": v.validation, "created_at": v.created_at, "score": after.total if after else None,
        "has_pdf": bool(v.pdf_path and v.pdf_path.endswith(".pdf")),
    }


# ---------------------------------------------------------------- tailoring

def tailor_job(db: Session, job: Job, use_llm: bool = True, build: bool = True) -> dict:
    facts = get_facts()
    master = ensure_master(db, facts)
    ex = get_extraction(db, job, use_llm)
    before = latest_score(db, job.id, master.id) or analyze_job(db, job, use_llm)

    t = tailor(ex, job.jd_text, facts, use_llm=use_llm)
    version = ResumeVersion(parent_id=master.id, job_id=job.id, objective=t.objective, skills_line=t.skills)
    db.add(version)
    db.flush()

    validation = t.validation.to_dict()
    files: dict = {}
    if build and t.validation.ok:
        files = build_and_check(facts, t.objective, t.skills, get_settings().output_dir, f"resume_{version.id}")
        validation = {
            "ok": validation["ok"] and files["validation"]["ok"],
            "errors": validation["errors"] + files["validation"]["errors"],
            "warnings": validation["warnings"] + files["validation"]["warnings"],
        }
        version.pdf_path = files.get("pdf_path") or files.get("docx_path")
    version.validation = {**validation, "source": t.source, "attempts": len(t.attempts), "role": t.role, "areas": t.areas, "tools": t.tools}

    after_text = render_resume_text(facts, t.objective, t.skills)
    after = score(ex, after_text, job.jd_text, facts, format_score(db))
    db.add(MatchScore(job_id=job.id, resume_version_id=version.id, total=after.total, breakdown=after.breakdown(), gaps=after.gaps_dict()))
    db.commit()

    return {
        "version": version_dict(db, version),
        "before": {"total": before.total, "breakdown": before.breakdown},
        "after": {"total": after.total, "breakdown": after.breakdown()},
        "master": {"objective": facts.resume.objective, "skills": facts.resume.skills},
        "gaps_to_disclose": [g for g in after.gaps_dict()["gap"] if g["required"]],
        "adjacent": after.gaps_dict()["adjacent"],
        "source": t.source,
        "llm_attempts": t.attempts,
    }


# ---------------------------------------------------------------- insights

def skill_demand(db: Session, min_score: float = 0) -> list[dict]:
    """Skills most requested across active jobs you'd want, split by whether you have them."""
    master = ensure_master(db)
    pool = get_facts().pool_names()
    rows = db.execute(
        select(JobRequirement.item, JobRequirement.required, func.count())
        .join(Job, Job.id == JobRequirement.job_id)
        .join(MatchScore, (MatchScore.job_id == Job.id) & (MatchScore.resume_version_id == master.id))
        .where(Job.active.is_(True), MatchScore.total >= min_score, JobRequirement.kind == "hard")
        .group_by(JobRequirement.item, JobRequirement.required)
    ).all()
    agg: dict[str, dict] = {}
    for item, required, n in rows:
        a = agg.setdefault(item, {"skill": item, "jobs": 0, "required_in": 0, "have": item in pool})
        a["jobs"] += n
        if required:
            a["required_in"] += n
    return sorted(agg.values(), key=lambda a: (-a["required_in"], -a["jobs"]))


def company_application_count(db: Session, company: str | None) -> int:
    if not company:
        return 0
    return db.scalar(
        select(func.count()).select_from(Application).join(Job, Job.id == Application.job_id)
        .where(func.lower(Job.company) == company.lower(), Application.status != "saved")
    ) or 0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
