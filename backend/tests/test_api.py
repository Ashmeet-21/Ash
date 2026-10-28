import io
import json

import httpx
import pytest

from app.sources import ats, link
from app.sources.base import html_to_text
from tests.conftest import FIXTURES


def _score(client, text, **kw):
    r = client.post("/jobs/score", json={"jd_text": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    assert client.get("/health").json()["ok"] is True


def test_score_paste_and_detail(client, soc_jd):
    d = _score(client, soc_jd, title="Junior SOC Analyst", company="Northwind Security")
    assert d["score"] > 55
    assert d["breakdown"]["hard_skills"]["weight"] == 40
    assert {"shown", "hidden", "adjacent", "gap"} == set(d["gaps"])
    assert "vancouver" in d["regions"]
    again = _score(client, soc_jd, title="Junior SOC Analyst", company="Northwind Security")
    assert again["id"] == d["id"]  # same JD -> same job, no duplicate
    assert client.get(f"/jobs/{d['id']}").json()["title"] == "Junior SOC Analyst"


def test_score_requires_input(client):
    assert client.post("/jobs/score", json={}).status_code == 422


def test_linkedin_link_refused(client):
    r = client.post("/jobs/score", json={"url": "https://www.linkedin.com/jobs/view/123"})
    assert r.status_code == 422
    assert "Paste" in r.json()["detail"]


def test_feed_filters(client, soc_jd):
    _score(client, soc_jd, title="Junior SOC Analyst", company="Northwind Security")
    _score(client, (FIXTURES / "senior_java.txt").read_text(), title="Senior Backend Engineer (Java)", company="Maple Bank")
    all_jobs = client.get("/jobs", params={"sort": "score"}).json()
    assert all_jobs["total"] >= 2
    scores = [j["score"] for j in all_jobs["items"] if not j["flag_counts"]["block"]]
    assert scores == sorted(scores, reverse=True)
    van = client.get("/jobs", params={"region": "vancouver"}).json()["items"]
    assert all("vancouver" in j["regions"] for j in van)
    assert not any(j["flag_counts"]["block"] for j in client.get("/jobs", params={"hide_blocked": True}).json()["items"])
    assert all(j["score"] >= 60 for j in client.get("/jobs", params={"min_score": 60}).json()["items"])


def test_tailor_flow_builds_files(client, soc_jd):
    job = _score(client, soc_jd, title="Junior SOC Analyst", company="Northwind Security")
    r = client.post(f"/tailor/{job['id']}")
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["version"]["validation"]["ok"], t["version"]["validation"]
    assert t["after"]["total"] > t["before"]["total"]
    assert t["source"] == "template"
    docx = client.get(f"/resume-versions/{t['version']['id']}/download", params={"fmt": "docx"})
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    detail = client.get(f"/jobs/{job['id']}").json()
    assert detail["tailored_versions"][0]["id"] == t["version"]["id"]


def test_tailor_warns_on_poor_fit(client, soc_jd):
    java = _score(client, (FIXTURES / "senior_java.txt").read_text(), title="Senior Java Engineer", company="Fit Test Bank")
    v = client.post(f"/tailor/{java['id']}").json()["version"]
    rules = [w["rule"] for w in v["validation"]["warnings"]]
    assert "knockout" in rules and "low_fit" in rules
    assert "Java" not in v["objective"]
    soc = _score(client, soc_jd + "\n(fit test)", title="Junior SOC Analyst", company="Fit Test Security")
    v = client.post(f"/tailor/{soc['id']}").json()["version"]
    assert not any(w["rule"] in ("knockout", "low_fit") for w in v["validation"]["warnings"])


def test_applications_lifecycle(client, soc_jd):
    job = _score(client, soc_jd + "\n(apps test)", title="Junior SOC Analyst", company="Apps Test Co")
    r = client.post("/applications", json={"job_id": job["id"], "status": "saved"})
    assert r.status_code == 200
    app_id = r.json()["id"]
    assert client.post("/applications", json={"job_id": job["id"]}).status_code == 409
    r = client.patch(f"/applications/{app_id}", json={"status": "applied", "notes": "Referred by alumni"})
    assert r.json()["status"] == "applied" and r.json()["applied_at"]
    assert any(a["id"] == app_id for a in client.get("/applications").json())
    assert client.delete(f"/jobs/{job['id']}").status_code == 409  # tracked jobs can't be deleted
    assert client.delete(f"/applications/{app_id}").json()["ok"]


def test_three_per_company_warning(client):
    ids = []
    for i in range(3):
        j = _score(client, f"Developer {i}\nRequirements:\n- Python\n- Docker\nLocation: Vancouver, BC\nUnique {i}", title=f"Developer {i}", company="Busy Corp")
        ids.append(client.post("/applications", json={"job_id": j["id"], "status": "applied"}).json())
    assert ids[-1]["warnings"]


def test_parse_check_docx_upload(client):
    from app.engine.document import build_docx
    from app.facts import get_facts

    f = get_facts()
    data = build_docx(f, f.resume.objective, f.resume.skills)
    r = client.post("/resume/parse-check", files={"file": ("resume.docx", data)}, params={"save": "false"})
    assert r.status_code == 200, r.text
    assert r.json()["format_score"] == 1.0


def test_parse_check_flags_two_columns(client):
    reportlab = pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 740
    for i in range(40):
        c.drawString(40, y, f"Left column skill line {i} Python")
        c.drawString(330, y, f"Right column bullet {i} Docker")
        y -= 16
    c.drawString(40, 770, "alex@example.com")
    c.save()
    r = client.post("/resume/parse-check", files={"file": ("cv.pdf", buf.getvalue())}, params={"save": "false"})
    checks = {c["key"]: c for c in r.json()["checks"]}
    assert checks["single_column"]["passed"] is False
    assert r.json()["format_score"] < 0.8
    assert reportlab


def test_insights(client, soc_jd):
    _score(client, soc_jd, title="Junior SOC Analyst", company="Northwind Security")
    skills = client.get("/insights/skills").json()
    assert any(s["skill"] == "SIEM" and s["have"] for s in skills)
    assert client.get("/insights/summary").json()["active_jobs"] >= 1


def test_api_token(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "api_token", "s3cret")
    assert client.get("/jobs").status_code == 401
    assert client.get("/jobs", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------- sources (mocked HTTP)

def _mock(monkeypatch, module, handler):
    def fake_client():
        return httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(module, "client", fake_client)


def test_greenhouse_parse(monkeypatch):
    payload = {"jobs": [{"id": 42, "title": "Security Analyst, New Grad", "location": {"name": "Vancouver, BC"},
                         "absolute_url": "https://boards.greenhouse.io/acme/jobs/42", "updated_at": "2026-10-01T12:00:00Z",
                         "content": "&lt;p&gt;We need &lt;strong&gt;Python&lt;/strong&gt;&lt;/p&gt;&lt;ul&gt;&lt;li&gt;SIEM&lt;/li&gt;&lt;/ul&gt;"}]}
    _mock(monkeypatch, ats, lambda req: httpx.Response(200, json=payload))
    jobs = ats.greenhouse("acme", "Acme")
    assert jobs[0].external_id == "acme:42"
    assert "Python" in jobs[0].jd_text and "- SIEM" in jobs[0].jd_text
    assert jobs[0].company == "Acme"


def test_lever_parse(monkeypatch):
    payload = [{"id": "abc", "text": "Junior Developer", "categories": {"location": "Noida"}, "hostedUrl": "https://jobs.lever.co/x/abc",
                "createdAt": 1790000000000, "descriptionPlain": "Build APIs.", "lists": [{"text": "Requirements", "content": "<li>FastAPI</li>"}],
                "additionalPlain": "", "workplaceType": "onsite", "salaryRange": {"min": 600000, "max": 900000, "currency": "INR"}}]
    _mock(monkeypatch, ats, lambda req: httpx.Response(200, json=payload))
    j = ats.lever("x", "X")[0]
    assert "Requirements" in j.jd_text and "FastAPI" in j.jd_text
    assert j.salary_currency == "INR" and j.posted_at.year == 2026


def test_ashby_parse(monkeypatch):
    payload = {"jobs": [{"id": "u1", "title": "AI Engineer", "location": "Dubai", "isRemote": False, "isListed": True,
                         "descriptionPlain": "Python, LLMs", "jobUrl": "https://jobs.ashbyhq.com/y/u1", "publishedAt": "2026-10-20T00:00:00Z"}]}
    _mock(monkeypatch, ats, lambda req: httpx.Response(200, json=payload))
    j = ats.ashby("y", "Y")[0]
    assert j.location == "Dubai" and j.jd_text == "Python, LLMs"


def test_link_jsonld(monkeypatch):
    posting = {"@context": "https://schema.org", "@type": "JobPosting", "title": "SOC Analyst", "description": "<p>Monitor SIEM alerts.</p>",
               "hiringOrganization": {"@type": "Organization", "name": "Example Corp"},
               "jobLocation": {"@type": "Place", "address": {"addressLocality": "Vancouver", "addressRegion": "BC"}}}
    page = f'<html><head><script type="application/ld+json">{json.dumps(posting)}</script></head><body>x</body></html>'
    _mock(monkeypatch, link, lambda req: httpx.Response(200, text=page))
    monkeypatch.setattr(link, "_assert_public", lambda host: None)
    j = link.fetch_link("https://careers.example.com/jobs/1")
    assert j.title == "SOC Analyst" and j.company == "Example Corp" and j.location == "Vancouver, BC"


def test_link_routes_greenhouse(monkeypatch):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"id": 7, "title": "Dev", "content": "Python", "location": {"name": "Remote"}})
    _mock(monkeypatch, ats, handler)
    j = link.fetch_link("https://job-boards.greenhouse.io/acme/jobs/7?gh_src=x")
    assert seen["url"].startswith("https://boards-api.greenhouse.io/v1/boards/acme/jobs/7")
    assert j.remote


def test_private_address_refused():
    with pytest.raises(link.SourceError):
        link.fetch_link("http://127.0.0.1:8000/admin")


def test_html_to_text():
    assert html_to_text("<h2>Requirements</h2><ul><li>Python</li><li>SQL</li></ul>") == "Requirements\n\n- Python\n- SQL"
