from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.config import get_settings
from app.db import SessionLocal, get_db, init_db
from app.engine.extract import jd_hash
from app.engine.parse_check import parse_check
from app.facts import get_facts
from app.llm import llm_available
from app.models import Application, Job, MatchScore, ResumeVersion
from app.regions import get_regions
from app.sources.base import JobIn, SourceError
from app.sources.link import fetch_link

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("jobmatch")


def _scheduled_ingest() -> None:
    db = SessionLocal()
    try:
        summary = services.ingest(db)
        log.info("Scheduled ingest: %s", {k: v for k, v in summary.items() if k != "new_matches"})
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        services.sync_profile_facts(db, get_facts())
        services.ensure_master(db)
    finally:
        db.close()
    scheduler = None
    settings = get_settings()
    if settings.scheduler:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()
        scheduler.add_job(_scheduled_ingest, "cron", hour=settings.ingest_cron_hour, minute=0)
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown()


app = FastAPI(title="JobMatch", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_token(authorization: str | None = Header(default=None)) -> None:
    token = get_settings().api_token
    if not token:
        return
    if not authorization or not secrets.compare_digest(authorization.removeprefix("Bearer ").strip(), token):
        raise HTTPException(401, "Missing or invalid API token.")


auth = [Depends(require_token)]


def get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job


# ---------------------------------------------------------------- meta

@app.get("/health")
def health():
    return {"ok": True, "llm": llm_available()}


@app.get("/profile", dependencies=auth)
def profile(db: Session = Depends(get_db)):
    facts = get_facts()
    master = services.ensure_master(db)
    return {
        "name": facts.profile.name,
        "graduation": facts.profile.graduation,
        "open_to_regions": facts.profile.open_to_regions,
        "target_titles": facts.profile.target_titles,
        "skill_pool": [s.model_dump() for s in facts.skill_pool],
        "master": {"id": master.id, "objective": master.objective, "skills": master.skills_line},
        "parse_check": (master.validation or {}).get("parse_check"),
        "regions": {k: r.label for k, r in get_regions().regions.items()},
        "llm": llm_available(),
    }


# ---------------------------------------------------------------- jobs

class ScoreIn(BaseModel):
    jd_text: str | None = Field(default=None, max_length=60000)
    url: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    use_llm: bool = True

    @model_validator(mode="after")
    def _one_of(self):
        if not (self.jd_text and self.jd_text.strip()) and not self.url:
            raise ValueError("Provide jd_text or url.")
        return self


@app.post("/jobs/score", dependencies=auth)
def score_job(body: ScoreIn, db: Session = Depends(get_db)):
    if body.jd_text and body.jd_text.strip():
        posting = JobIn(
            source="paste",
            external_id=jd_hash(body.jd_text)[:24],
            title=(body.title or "").strip(),
            jd_text=body.jd_text.strip(),
            company=body.company or None,
            location=body.location or None,
            url=body.url or None,
        )
    else:
        try:
            posting = fetch_link(body.url)
        except SourceError as e:
            raise HTTPException(422, str(e)) from e
        posting.title = body.title or posting.title
        posting.company = body.company or posting.company
        posting.location = body.location or posting.location
    if not posting.jd_text.strip():
        raise HTTPException(422, "No job description text found.")
    job = services.score_posting(db, posting, use_llm=body.use_llm)
    return services.job_detail(db, job)


@app.post("/jobs/ingest", dependencies=auth)
def ingest_jobs(use_llm: bool = True, db: Session = Depends(get_db)):
    return services.ingest(db, use_llm=use_llm)


@app.get("/jobs", dependencies=auth)
def list_jobs(
    db: Session = Depends(get_db),
    min_score: float = 0,
    region: str | None = None,
    remote: bool | None = None,
    role_type: Literal["co-op", "new-grad", "other"] | None = None,
    posted_within_days: int | None = None,
    salary_min: float | None = None,
    q: str | None = None,
    hide_blocked: bool = False,
    include_closed: bool = False,
    sort: Literal["score", "newest"] = "score",
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    master = services.ensure_master(db)
    stmt = select(Job)
    if not include_closed:
        stmt = stmt.where(Job.active.is_(True))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where((Job.title.ilike(like)) | (Job.company.ilike(like)))
    if posted_within_days:
        since = datetime.now(timezone.utc) - timedelta(days=posted_within_days)
        stmt = stmt.where((Job.posted_at >= since) | (Job.posted_at.is_(None) & (Job.first_seen_at >= since)))
    if salary_min:
        stmt = stmt.where(Job.salary_max >= salary_min)
    rows = []
    for job in db.scalars(stmt).all():
        s = services.job_summary(db, job, master.id)
        if s["score"] is None or s["score"] < min_score:
            continue
        if region and region not in s["regions"]:
            continue
        if remote is not None and s["remote"] != remote:
            continue
        if role_type and s["role_type"] != role_type:
            continue
        if hide_blocked and s["flag_counts"]["block"]:
            continue
        rows.append(s)
    if sort == "newest":
        rows.sort(key=lambda r: r["posted_at"] or r["first_seen_at"], reverse=True)
    else:
        rows.sort(key=lambda r: (r["flag_counts"]["block"] > 0, -(r["score"] or 0)))
    return {"total": len(rows), "items": rows[offset: offset + limit]}


@app.get("/jobs/{job_id}", dependencies=auth)
def job_detail(job_id: int, db: Session = Depends(get_db)):
    return services.job_detail(db, get_job(db, job_id))


@app.post("/jobs/{job_id}/rescore", dependencies=auth)
def rescore(job_id: int, use_llm: bool = True, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    services.analyze_job(db, job, use_llm)
    return services.job_detail(db, job)


@app.delete("/jobs/{job_id}", dependencies=auth)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if db.scalar(select(Application).where(Application.job_id == job_id)):
        raise HTTPException(409, "This job is in your tracker; remove the application first.")
    db.query(ResumeVersion).filter(ResumeVersion.job_id == job_id).delete()
    db.delete(job)
    db.commit()
    return {"ok": True}


@app.get("/alerts", dependencies=auth)
def alerts(since_hours: int = 24, db: Session = Depends(get_db)):
    """New matching roles first seen in the window, best first. Feed this to a phone digest."""
    master = services.ensure_master(db)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    out = []
    for job in db.scalars(select(Job).where(Job.active.is_(True), Job.first_seen_at >= since)).all():
        s = services.job_summary(db, job, master.id)
        if (s["score"] or 0) >= get_settings().alert_min_score and not s["flag_counts"]["block"]:
            out.append(s)
    return sorted(out, key=lambda s: -s["score"])


# ---------------------------------------------------------------- tailoring

@app.post("/tailor/{job_id}", dependencies=auth)
def tailor_job(job_id: int, use_llm: bool = True, db: Session = Depends(get_db)):
    return services.tailor_job(db, get_job(db, job_id), use_llm=use_llm)


@app.get("/resume-versions/{version_id}/download", dependencies=auth)
def download(version_id: int, fmt: Literal["pdf", "docx"] = "pdf", db: Session = Depends(get_db)):
    v = db.get(ResumeVersion, version_id)
    if not v or not v.pdf_path:
        raise HTTPException(404, "No built file for this version (it may have failed validation).")
    path = Path(v.pdf_path).with_suffix(f".{fmt}")
    if not path.exists():
        raise HTTPException(404, f"No {fmt.upper()} file (LibreOffice may be missing for PDF).")
    facts = get_facts()
    job = db.get(Job, v.job_id) if v.job_id else None
    name = "_".join(x for x in [facts.profile.name.replace(" ", "_"), "Resume", (job.company or "").replace(" ", "_") if job else ""] if x)
    media = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path, media_type=media, filename=f"{name}.{fmt}")


@app.post("/resume/parse-check", dependencies=auth)
async def resume_parse_check(file: UploadFile = File(...), save: bool = True, db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > 10_000_000:
        raise HTTPException(413, "File too large (10 MB max).")
    try:
        result = parse_check(file.filename or "", data).to_dict()
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # corrupt file
        raise HTTPException(422, f"Could not read the file: {e}") from e
    if save:
        services.save_parse_check(db, result)
    return result


# ---------------------------------------------------------------- applications

Status = Literal["saved", "applied", "interview", "offer", "rejected", "withdrawn"]


class ApplicationIn(BaseModel):
    job_id: int
    status: Status = "saved"
    resume_version_id: int | None = None
    applied_at: datetime | None = None
    deadline: datetime | None = None
    notes: str | None = None


class ApplicationPatch(BaseModel):
    status: Status | None = None
    resume_version_id: int | None = None
    applied_at: datetime | None = None
    deadline: datetime | None = None
    notes: str | None = None


def application_dict(db: Session, a: Application) -> dict:
    ms = services.latest_score(db, a.job_id, a.resume_version_id) if a.resume_version_id else services.latest_score(db, a.job_id)
    return {
        "id": a.id, "job_id": a.job_id, "status": a.status, "resume_version_id": a.resume_version_id,
        "applied_at": a.applied_at, "deadline": a.deadline, "notes": a.notes, "updated_at": a.updated_at,
        "job": {"title": a.job.title, "company": a.job.company, "location": a.job.location, "url": a.job.url, "active": a.job.active},
        "score": ms.total if ms else None,
    }


def _warnings(db: Session, a: Application) -> list[str]:
    n = services.company_application_count(db, a.job.company)
    return [f"You have applied to {n} roles at {a.job.company}; many companies cap or frown on more than 2-3."] if n >= 3 else []


@app.get("/applications", dependencies=auth)
def list_applications(db: Session = Depends(get_db)):
    rows = db.scalars(select(Application).order_by(Application.updated_at.desc())).all()
    return [application_dict(db, a) for a in rows]


@app.post("/applications", dependencies=auth)
def create_application(body: ApplicationIn, db: Session = Depends(get_db)):
    get_job(db, body.job_id)
    existing = db.scalar(select(Application).where(Application.job_id == body.job_id))
    if existing:
        raise HTTPException(409, f"Already tracked as application {existing.id}.")
    a = Application(**body.model_dump())
    if a.status == "applied" and not a.applied_at:
        a.applied_at = datetime.now(timezone.utc)
    db.add(a)
    db.commit()
    return {**application_dict(db, a), "warnings": _warnings(db, a)}


@app.patch("/applications/{app_id}", dependencies=auth)
def update_application(app_id: int, body: ApplicationPatch, db: Session = Depends(get_db)):
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404, "Application not found.")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    if a.status == "applied" and not a.applied_at:
        a.applied_at = datetime.now(timezone.utc)
    db.commit()
    return {**application_dict(db, a), "warnings": _warnings(db, a)}


@app.delete("/applications/{app_id}", dependencies=auth)
def delete_application(app_id: int, db: Session = Depends(get_db)):
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404, "Application not found.")
    db.delete(a)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- insights

@app.get("/insights/skills", dependencies=auth)
def insights_skills(min_score: float = 0, db: Session = Depends(get_db)):
    return services.skill_demand(db, min_score)


@app.get("/insights/summary", dependencies=auth)
def insights_summary(db: Session = Depends(get_db)):
    master = services.ensure_master(db)
    scores = db.scalars(select(MatchScore.total).join(Job).where(MatchScore.resume_version_id == master.id, Job.active.is_(True))).all()
    apps = db.scalars(select(Application)).all()
    by_status: dict[str, int] = {}
    for a in apps:
        by_status[a.status] = by_status.get(a.status, 0) + 1
    return {
        "active_jobs": len(scores),
        "strong_matches": sum(1 for s in scores if s >= get_settings().alert_min_score),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "applications": by_status,
    }
