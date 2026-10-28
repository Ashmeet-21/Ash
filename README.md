# JobMatch

A resume-aware job finder and ATS coach. It finds entry-level roles, scores each one the way an
ATS and a recruiter would, flags the things that actually get applications rejected, and tailors
your resume for the job without breaking your locked resume rules.

**The loop:** find → score → fix → track.

| | What it does |
|---|---|
| **Score** | Paste a JD or link. 0-100 match score with a breakdown, plus a *tailored* score (what you'd score once Objective and Skills fit the job). |
| **Gaps** | Every requirement is classed as *shown*, *hidden* (in your pool, not on this resume), *adjacent* (related evidence, a cover-letter angle) or a *true gap* (never added). |
| **Knockouts** | Graduation window, sponsorship and work authorization, location, language, years, degree level, term length, enrollment, seniority. Shown separately; never averaged into the score. |
| **Tailor** | Rewrites only Objective and Skills, from your evidenced skill pool only. A deterministic validator rejects any draft that adds a skill, overclaims, uses an em dash, or changes locked text. Builds DOCX + PDF and re-validates what a parser reads back. |
| **Parse check** | Upload your PDF/DOCX and see what an ATS extracts: columns, tables, images, text boxes, contact in headers. |
| **Find** | Daily pull from Greenhouse, Lever and Ashby boards on your watchlist, plus Adzuna. Dedupes the same role across sources and closes postings that disappear. |
| **Track** | Applications with status, deadlines, notes, and a warning at 3+ applications to one company. |
| **Insights** | Skills you lack, ranked by how often the jobs you want require them. |

## Stack

- **Backend:** Python 3.13, FastAPI, SQLAlchemy. Python because the hardest parts (PDF layout parsing with pdfplumber, text matching) have the best libraries there.
- **Database:** SQLite for zero-setup local use, PostgreSQL in production (same code, verified on both).
- **Documents:** python-docx, LibreOffice for PDF.
- **Frontend:** Next.js 16, React 19, Tailwind 4. Works on a phone.
- **Claude (optional):** Claude Haiku 5.5 for JD extraction and Claude Sonnet 5.5 for Objective drafts. Without an API key, the rule-based extractor and template tailor run instead; everything still works.

## Quick start

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp data/facts.example.yaml data/facts.yaml          # then fill in your real resume
cp data/watchlist.example.yaml data/watchlist.yaml  # companies to watch
uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. API docs are at http://localhost:8000/docs.

Or run everything (PostgreSQL + API + dashboard) with Docker:

```bash
docker compose up --build
```

## Your data

- `backend/data/facts.yaml` is the single source of truth: profile and eligibility facts, the
  **evidenced skill pool** (each skill lists the project/role that proves it), the master
  Objective and Skills, and the locked Projects / Experience / Education text.
  The `.example` file is a fictional student; replace every value.
- `facts.yaml`, `watchlist.yaml`, `regions.yaml`, the database and built resumes are git-ignored.
- Contact details never go into Claude prompts.

## Environment

See `backend/.env.example`. The important ones:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Enables Claude extraction and drafting (optional) |
| `JOBMATCH_DATABASE_URL` | `postgresql+psycopg://...` in production |
| `JOBMATCH_API_TOKEN` | Require a bearer token on every endpoint (set it before exposing the API) |
| `JOBMATCH_SCHEDULER=true` | Daily ingest inside the API process |
| `JOBMATCH_ADZUNA_APP_ID` / `_APP_KEY` | Adzuna aggregator (free for personal use) |

## How the score works

| Component | Weight | Measured as |
|---|---|---|
| Required hard skills | 40 | Matched / required via the alias map; must-haves count 2x nice-to-haves |
| Semantic fit | 20 | Resume vs JD similarity (lexical by default; local embeddings if `fastembed` is installed and `JOBMATCH_EMBEDDING_MODEL` is set) |
| Title and level fit | 15 | Fuzzy match to your target titles; penalties for senior titles and years above yours |
| Preferred skills and keywords | 10 | Coverage with each term capped at 3, so stuffing doesn't help |
| Parse and format | 10 | From your last parse check |
| Education and certs | 5 | Only when the JD asks; otherwise left out and the rest renormalized |

The weights are a starting point. Phase 1's gate is agreement with your own judgment:
add 30+ real JDs you have already judged to `backend/data/golden/` (see its README) and run

```bash
python scripts/evaluate.py
```

## Tests

```bash
cd backend && python -m pytest -q      # engine, API, sources (mocked HTTP), ingest
cd frontend && npm run lint && npm run build
```

CI runs both on every push.

## Job sources

Public company ATS boards (Greenhouse, Lever, Ashby) need no key. LinkedIn, Indeed, Naukri,
Bayt and GulfTalent have no open API and are never scraped; paste those JDs as text. Adzuna
returns only a snippet, so those scores are rough until you paste the full JD; its results
carry the required "Jobs by Adzuna" attribution in the dashboard.

## Deploy

- **API:** the `backend/Dockerfile` (includes LibreOffice) on Render or any Docker host. Set
  `JOBMATCH_DATABASE_URL`, `JOBMATCH_API_TOKEN`, `JOBMATCH_CORS_ORIGINS`, and mount or bake in
  your `data/facts.yaml`.
- **Dashboard:** Netlify (`frontend/netlify.toml`) or the `frontend/Dockerfile`. Set
  `NEXT_PUBLIC_API_URL`, then enter the API token on the Settings page.
