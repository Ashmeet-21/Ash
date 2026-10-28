"""Public company job boards: Greenhouse, Lever and Ashby. No auth; one board per company."""

from __future__ import annotations

import httpx

from app.sources.base import JobIn, SourceError, client, html_to_text, parse_dt


def _get_json(url: str, params: dict | None = None):
    try:
        with client() as c:
            r = c.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        raise SourceError(f"{url} returned {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise SourceError(f"{url}: {e}") from e


def _greenhouse_job(j: dict, company: str | None, board: str) -> JobIn:
    loc = (j.get("location") or {}).get("name")
    return JobIn(
        source="greenhouse",
        external_id=f"{board}:{j['id']}",
        title=j.get("title", "").strip(),
        jd_text=html_to_text(j.get("content") or ""),
        company=company or (j.get("company_name")),
        location=loc,
        remote=bool(loc and "remote" in loc.lower()),
        url=j.get("absolute_url"),
        posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
    )


def greenhouse(board: str, company: str | None = None) -> list[JobIn]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", {"content": "true"})
    return [_greenhouse_job(j, company, board) for j in data.get("jobs", [])]


def greenhouse_one(board: str, job_id: str) -> JobIn:
    j = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}")
    return _greenhouse_job(j, None, board)


def _lever_job(p: dict, company: str | None, board: str) -> JobIn:
    parts = [p.get("descriptionPlain") or html_to_text(p.get("description") or "")]
    for block in p.get("lists") or []:
        parts.append(block.get("text", ""))
        parts.append(html_to_text("<ul>" + (block.get("content") or "") + "</ul>"))
    parts.append(p.get("additionalPlain") or html_to_text(p.get("additional") or ""))
    cats = p.get("categories") or {}
    loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
    salary = p.get("salaryRange") or {}
    return JobIn(
        source="lever",
        external_id=f"{board}:{p['id']}",
        title=(p.get("text") or "").strip(),
        jd_text="\n\n".join(x for x in parts if x).strip(),
        company=company,
        location=loc or None,
        remote=(p.get("workplaceType") == "remote") or bool(loc and "remote" in loc.lower()),
        url=p.get("hostedUrl"),
        posted_at=parse_dt(p.get("createdAt")),
        salary_min=salary.get("min"),
        salary_max=salary.get("max"),
        salary_currency=salary.get("currency"),
    )


def lever(board: str, company: str | None = None) -> list[JobIn]:
    data = _get_json(f"https://api.lever.co/v0/postings/{board}", {"mode": "json"})
    return [_lever_job(p, company, board) for p in data]


def lever_one(board: str, posting_id: str) -> JobIn:
    return _lever_job(_get_json(f"https://api.lever.co/v0/postings/{board}/{posting_id}", {"mode": "json"}), None, board)


def _ashby_job(j: dict, company: str | None, board: str) -> JobIn:
    locs = [j.get("location")] + [s.get("location") for s in j.get("secondaryLocations") or [] if isinstance(s, dict)]
    loc = ", ".join(x for x in locs if x)
    comp = j.get("compensation") or {}
    smin = smax = cur = None
    for tier in comp.get("summaryComponents") or []:
        if tier.get("compensationType") == "Salary":
            smin, smax, cur = tier.get("minValue"), tier.get("maxValue"), tier.get("currencyCode")
            break
    return JobIn(
        source="ashby",
        external_id=f"{board}:{j['id']}",
        title=(j.get("title") or "").strip(),
        jd_text=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml") or ""),
        company=company,
        location=loc or None,
        remote=bool(j.get("isRemote")) or j.get("workplaceType") == "Remote",
        url=j.get("jobUrl") or j.get("applyUrl"),
        posted_at=parse_dt(j.get("publishedAt")),
        salary_min=smin,
        salary_max=smax,
        salary_currency=cur,
    )


def ashby(board: str, company: str | None = None) -> list[JobIn]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}", {"includeCompensation": "true"})
    return [_ashby_job(j, company, board) for j in data.get("jobs", []) if j.get("isListed", True)]


def ashby_one(board: str, job_id: str) -> JobIn:
    for j in ashby(board):
        if j.external_id == f"{board}:{job_id}":
            return j
    raise SourceError("Posting not found on that Ashby board (it may have closed).")


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}
