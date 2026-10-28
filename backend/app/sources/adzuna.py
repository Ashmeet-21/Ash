"""Adzuna aggregator. Free key for personal evaluation; results must show an Adzuna link.

Adzuna returns only a description snippet, so scores for these jobs are rougher until you
open the posting and paste the full JD.
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.regions import get_regions
from app.sources.base import JobIn, SourceError, client, html_to_text, parse_dt


def adzuna(region: str, what: str, max_days_old: int = 14, pages: int = 2) -> list[JobIn]:
    s = get_settings()
    if not (s.adzuna_app_id and s.adzuna_app_key):
        raise SourceError("Adzuna keys not configured (JOBMATCH_ADZUNA_APP_ID / JOBMATCH_ADZUNA_APP_KEY).")
    r = get_regions().regions.get(region)
    if not r or not r.adzuna:
        raise SourceError(f"Region '{region}' has no Adzuna settings in regions.yaml.")
    out: list[JobIn] = []
    with client() as c:
        for page in range(1, pages + 1):
            try:
                resp = c.get(
                    f"https://api.adzuna.com/v1/api/jobs/{r.adzuna['country']}/search/{page}",
                    params={
                        "app_id": s.adzuna_app_id,
                        "app_key": s.adzuna_app_key,
                        "what": what,
                        "where": r.adzuna.get("where", ""),
                        "results_per_page": 50,
                        "max_days_old": max_days_old,
                        "content-type": "application/json",
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise SourceError(f"Adzuna: {e}") from e
            results = resp.json().get("results", [])
            for j in results:
                out.append(JobIn(
                    source="adzuna",
                    external_id=str(j["id"]),
                    title=html_to_text(j.get("title", "")),
                    jd_text=html_to_text(j.get("description", "")),
                    company=(j.get("company") or {}).get("display_name"),
                    location=(j.get("location") or {}).get("display_name"),
                    url=j.get("redirect_url"),
                    posted_at=parse_dt(j.get("created")),
                    salary_min=j.get("salary_min"),
                    salary_max=j.get("salary_max"),
                    extra={"attribution": "Jobs by Adzuna", "snippet_only": True},
                ))
            if len(results) < 50:
                break
    return out
