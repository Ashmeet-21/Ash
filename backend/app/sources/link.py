"""Fetch a single posting from a pasted link.

Greenhouse, Lever and Ashby links go through their public APIs. Other career pages are
fetched once and read from their schema.org JobPosting data or visible text. Boards with
no open route (LinkedIn, Indeed, Naukri, Bayt, GulfTalent, Glassdoor) are not fetched:
paste the JD text instead.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from urllib.parse import urlparse

import httpx

from app.sources import ats
from app.sources.base import JobIn, SourceError, client, html_to_text, parse_dt

NO_SCRAPE = ("linkedin.com", "indeed.", "naukri.com", "bayt.com", "gulftalent.com", "glassdoor.")
MAX_BYTES = 3_000_000

GH = re.compile(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/([\w-]+)/jobs/(\d+)")
GH_EMBED = re.compile(r"greenhouse\.io/embed/job_app\?.*?for=([\w-]+).*?token=(\d+)")
LEVER = re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w.-]+)/([0-9a-f-]{36})")
ASHBY = re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)/([0-9a-f-]{36})")


def _assert_public(host: str) -> None:
    """Refuse links that resolve to private or local addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise SourceError(f"Cannot resolve {host}.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise SourceError("That link points to a private address.")


def _jsonld_posting(html: str) -> dict | None:
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if item.get("@type") in ("JobPosting", ["JobPosting"]):
                    return item
                stack.extend(v for v in item.values() if isinstance(v, (list, dict)))
            elif isinstance(item, list):
                stack.extend(item)
    return None


def _location_from_ld(p: dict) -> str | None:
    locs = p.get("jobLocation")
    locs = locs if isinstance(locs, list) else [locs] if locs else []
    names = []
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, dict):
            names.append(", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else None] if x))
    return "; ".join(n for n in names if n) or None


def fetch_link(url: str) -> JobIn:
    url = url.strip()
    if not re.match(r"https?://", url):
        url = "https://" + url
    if m := GH.search(url):
        return ats.greenhouse_one(m.group(1), m.group(2))
    if m := GH_EMBED.search(url):
        return ats.greenhouse_one(m.group(1), m.group(2))
    if m := LEVER.search(url):
        return ats.lever_one(m.group(1), m.group(2))
    if m := ASHBY.search(url):
        return ats.ashby_one(m.group(1), m.group(2))

    host = urlparse(url).hostname or ""
    if any(b in host for b in NO_SCRAPE):
        raise SourceError(f"{host} has no open API and scraping it breaks its terms. Paste the job description text instead.")
    _assert_public(host)
    try:
        with client() as c:
            r = c.get(url)
            r.raise_for_status()
            raw = r.text[:MAX_BYTES]
    except httpx.HTTPError as e:
        raise SourceError(f"Could not fetch the page: {e}") from e

    ext_id = hashlib.sha1(url.encode()).hexdigest()[:16]
    posting = _jsonld_posting(raw)
    if posting:
        org = posting.get("hiringOrganization") or {}
        salary = (posting.get("baseSalary") or {}) if isinstance(posting.get("baseSalary"), dict) else {}
        val = salary.get("value") or {}
        return JobIn(
            source="link",
            external_id=ext_id,
            title=html_to_text(posting.get("title") or ""),
            jd_text=html_to_text(posting.get("description") or ""),
            company=org.get("name") if isinstance(org, dict) else None,
            location=_location_from_ld(posting),
            remote=posting.get("jobLocationType") == "TELECOMMUTE",
            url=url,
            posted_at=parse_dt(posting.get("datePosted")),
            salary_min=val.get("minValue") if isinstance(val, dict) else None,
            salary_max=val.get("maxValue") if isinstance(val, dict) else None,
            salary_currency=salary.get("currency"),
        )

    text = html_to_text(raw)
    if len(text) < 400:
        raise SourceError("The page has too little readable text (it may load the job with JavaScript). Paste the JD text instead.")
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    return JobIn(source="link", external_id=ext_id, title=html_to_text(title_m.group(1)) if title_m else "", jd_text=text, url=url)
