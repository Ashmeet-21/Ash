from datetime import datetime, timezone

from sqlalchemy import select

from app import services
from app.db import SessionLocal, init_db
from app.models import Job
from app.sources.base import JobIn


def _posting(ext, title="Junior Security Analyst", company="Acme", location="Vancouver, BC", text=None):
    return JobIn(source="greenhouse", external_id=f"acme:{ext}", title=title, company=company, location=location,
                 jd_text=text or "Requirements:\n- SIEM and Python\n- Linux\nLocation: Vancouver, BC", posted_at=datetime.now(timezone.utc))


def test_ingest_dedupes_and_closes(monkeypatch):
    init_db()
    db = SessionLocal()
    watch = {"companies": [{"name": "Acme", "ats": "greenhouse", "board": "acme"}], "title_include": ["analyst", "developer"], "title_exclude": ["senior"]}
    monkeypatch.setattr(services, "load_watchlist", lambda: watch)

    batch = [
        _posting(1),
        _posting(2, title="Senior Security Analyst"),  # excluded by title
        _posting(3, title="Junior Developer", text="Requirements:\n- Python and FastAPI\n- Docker"),
    ]
    monkeypatch.setitem(services.FETCHERS, "greenhouse", lambda board, name: batch)
    s1 = services.ingest(db, use_llm=False)
    assert s1["kept"] == 2 and s1["new"] == 2 and not s1["errors"]

    # Same role from a second source is a duplicate, not a new job.
    dup = JobIn(source="lever", external_id="acme:zzz", title="Junior Security Analyst", company="ACME", location="Vancouver, BC", jd_text="short")
    _, status = services.upsert_job(db, dup)
    assert status == "duplicate"

    # Next run: posting 3 disappeared from the board, so it is closed.
    monkeypatch.setitem(services.FETCHERS, "greenhouse", lambda board, name: [_posting(1)])
    s2 = services.ingest(db, use_llm=False)
    assert s2["new"] == 0 and s2["closed"] == 1
    closed = db.scalar(select(Job).where(Job.external_id == "acme:3"))
    assert closed.active is False
    db.close()


def test_source_errors_are_reported(monkeypatch):
    from app.sources.base import SourceError

    db = SessionLocal()
    monkeypatch.setattr(services, "load_watchlist", lambda: {"companies": [{"name": "Broken", "ats": "lever", "board": "nope"}]})

    def boom(board, name):
        raise SourceError("404")
    monkeypatch.setitem(services.FETCHERS, "lever", boom)
    s = services.ingest(db, use_llm=False)
    assert s["errors"] == ["Broken: 404"]
    db.close()
