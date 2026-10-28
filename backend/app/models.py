"""The seven tables from the design doc.

`profile_facts` is synced from the facts YAML at startup; the YAML stays the editable source of truth.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# JSONB on PostgreSQL, plain JSON elsewhere.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProfileFact(Base):
    __tablename__ = "profile_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    skill: Mapped[str] = mapped_column(String(120), unique=True)
    evidence: Mapped[list] = mapped_column(JSONType, default=list)
    aliases: Mapped[list] = mapped_column(JSONType, default=list)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("resume_versions.id"), nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    objective: Mapped[str] = mapped_column(Text)
    skills_line: Mapped[dict] = mapped_column(JSONType)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jd_text: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), index=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    extraction_cache: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    requirements: Mapped[list["JobRequirement"]] = relationship(cascade="all, delete-orphan")
    scores: Mapped[list["MatchScore"]] = relationship(cascade="all, delete-orphan")
    flags: Mapped[list["Flag"]] = relationship(cascade="all, delete-orphan")


class JobRequirement(Base):
    __tablename__ = "job_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    item: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # hard | soft | education | eligibility
    required: Mapped[bool] = mapped_column(Boolean, default=True)


class MatchScore(Base):
    __tablename__ = "match_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    resume_version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_versions.id"), nullable=True)
    total: Mapped[float] = mapped_column(Float, index=True)
    breakdown: Mapped[dict] = mapped_column(JSONType)
    gaps: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))  # block | warn | info
    evidence_text: Mapped[str] = mapped_column(Text)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    resume_version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="saved")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    job: Mapped[Job] = relationship()
