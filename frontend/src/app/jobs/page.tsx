"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Empty, ErrorBox, ScoreBadge, SeverityChip, Spinner, errMsg, fmtDate, fmtSalary } from "@/components/ui";
import { api, type IngestSummary, type JobSummary } from "@/lib/api";
import { useHydrated, useLoad } from "@/lib/hooks";

const FILTER_KEY = "jobmatch.feedFilters";

interface Filters {
  q: string;
  region: string;
  role_type: string;
  remote: string;
  min_score: number;
  posted_within_days: string;
  hide_blocked: boolean;
  sort: "potential" | "score" | "newest";
}

const DEFAULTS: Filters = { q: "", region: "", role_type: "", remote: "", min_score: 0, posted_within_days: "", hide_blocked: true, sort: "potential" };

function loadFilters(): Filters {
  try {
    return { ...DEFAULTS, ...JSON.parse(window.localStorage.getItem(FILTER_KEY) || "{}") };
  } catch {
    return DEFAULTS;
  }
}

export default function FeedPage() {
  // Filters are remembered in browser storage, so render after hydration.
  return useHydrated() ? <Feed /> : <Spinner label="Loading..." />;
}

function Feed() {
  const [filters, setFilters] = useState<Filters>(loadFilters);
  const regions = useLoad(() => api.profile().then((p) => p.regions), []).data ?? {};
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [summary, setSummary] = useState<IngestSummary | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await api.jobs({
        q: filters.q || undefined,
        region: filters.region || undefined,
        role_type: filters.role_type || undefined,
        remote: filters.remote === "" ? undefined : filters.remote === "yes",
        min_score: filters.min_score || undefined,
        posted_within_days: filters.posted_within_days || undefined,
        hide_blocked: filters.hide_blocked,
        sort: filters.sort,
      });
      setJobs(res.items);
    } catch (e) {
      setError(errMsg(e));
      setJobs([]);
    }
  }, [filters]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    try {
      window.localStorage.setItem(FILTER_KEY, JSON.stringify(filters));
    } catch {
      /* ignore */
    }
    return () => clearTimeout(t);
  }, [load, filters]);

  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setFilters((f) => ({ ...f, [k]: v }));

  async function ingest() {
    setIngesting(true);
    setError(null);
    try {
      setSummary(await api.ingest());
      await load();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ranked feed</h1>
          <p className="text-sm text-zinc-500">Jobs from your watchlist and pasted links, ranked by score after tailoring.</p>
        </div>
        <button className="btn btn-primary" onClick={ingest} disabled={ingesting}>
          {ingesting && <Spinner />}
          Fetch new jobs
        </button>
      </div>

      {summary && (
        <div className="card text-sm">
          <p>
            Fetched {summary.fetched}, kept {summary.kept}: <b>{summary.new} new</b>, {summary.updated} updated, {summary.duplicates} duplicates, {summary.closed} closed.
          </p>
          {summary.new_matches.length > 0 && <p className="mt-1 text-emerald-700 dark:text-emerald-400">{summary.new_matches.length} new strong matches.</p>}
          {summary.errors.length > 0 && <p className="mt-1 text-rose-600">Errors: {summary.errors.join("; ")}</p>}
        </div>
      )}

      <div className="card grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <input className="input sm:col-span-2" placeholder="Search title or company" value={filters.q} onChange={(e) => set("q", e.target.value)} />
        <select className="input" value={filters.region} onChange={(e) => set("region", e.target.value)} aria-label="Region">
          <option value="">All regions</option>
          {Object.entries(regions).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <select className="input" value={filters.role_type} onChange={(e) => set("role_type", e.target.value)} aria-label="Role type">
          <option value="">All role types</option>
          <option value="new-grad">New grad / junior</option>
          <option value="co-op">Co-op / intern</option>
          <option value="other">Other</option>
        </select>
        <select className="input" value={filters.remote} onChange={(e) => set("remote", e.target.value)} aria-label="Remote">
          <option value="">Remote or on-site</option>
          <option value="yes">Remote only</option>
          <option value="no">On-site / hybrid</option>
        </select>
        <select className="input" value={filters.posted_within_days} onChange={(e) => set("posted_within_days", e.target.value)} aria-label="Posted">
          <option value="">Any date</option>
          <option value="1">Last 24 hours</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
        </select>
        <select className="input" value={filters.sort} onChange={(e) => set("sort", e.target.value as Filters["sort"])} aria-label="Sort">
          <option value="potential">Best fit (tailored)</option>
          <option value="score">Current score</option>
          <option value="newest">Newest</option>
        </select>
        <label className="flex items-center gap-2 text-sm">
          <span className="whitespace-nowrap text-zinc-500">Min {filters.min_score}</span>
          <input type="range" min={0} max={90} step={5} value={filters.min_score} onChange={(e) => set("min_score", Number(e.target.value))} className="w-full" />
        </label>
        <label className="flex items-center gap-2 text-sm sm:col-span-2 lg:col-span-4">
          <input type="checkbox" checked={filters.hide_blocked} onChange={(e) => set("hide_blocked", e.target.checked)} />
          Hide jobs with knockout risks
        </label>
      </div>

      <ErrorBox error={error} />
      {jobs === null && <Spinner label="Loading..." />}
      {jobs && jobs.length === 0 && !error && (
        <Empty>
          No jobs match. Add companies to <code>backend/data/watchlist.yaml</code> and press <b>Fetch new jobs</b>, or score a pasted JD.
        </Empty>
      )}
      <ul className="space-y-2">
        {jobs?.map((j) => (
          <li key={j.id}>
            <Link href={`/jobs/${j.id}`} className="card flex items-center gap-3 transition hover:border-indigo-400">
              <ScoreBadge score={j.potential ?? j.score} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{j.title}</p>
                <p className="truncate text-sm text-zinc-500">
                  {[j.company, j.location, j.remote ? "Remote" : null, fmtSalary(j.salary)].filter(Boolean).join(" · ")}
                </p>
                <div className="mt-1 flex flex-wrap gap-1.5 text-xs text-zinc-500">
                  {j.flag_counts.block > 0 && <SeverityChip severity="block">{j.flag_counts.block} knockout</SeverityChip>}
                  {j.flag_counts.warn > 0 && <SeverityChip severity="warn">{j.flag_counts.warn} warning</SeverityChip>}
                  {j.application_status && <span className="chip bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300">{j.application_status}</span>}
                  {j.role_type !== "other" && <span className="chip bg-zinc-100 dark:bg-zinc-800">{j.role_type}</span>}
                  <span>{j.source}</span>
                  <span>{fmtDate(j.posted_at || j.first_seen_at)}</span>
                </div>
              </div>
              <div className="hidden text-right text-xs text-zinc-500 sm:block">
                now {j.score === null ? "-" : Math.round(j.score)}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
