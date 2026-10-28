"use client";

import Link from "next/link";
import { useState } from "react";

import { api, type Breakdown, type Flag, type GapItem, type Gaps, type JobDetail, type TailorResult } from "@/lib/api";

import { ErrorBox, ScoreBadge, Section, SeverityChip, Spinner, errMsg, fmtDate, fmtSalary } from "./ui";

const COMPONENT_LABELS: Record<string, string> = {
  hard_skills: "Required hard skills",
  semantic: "Semantic fit",
  title_level: "Title and level fit",
  keywords: "Preferred skills and keywords",
  format: "Parse and format",
  education: "Education and certs",
};

export function BreakdownBars({ breakdown, compare }: { breakdown: Breakdown; compare?: Breakdown }) {
  const keys = Object.keys(breakdown).filter((k) => !k.startsWith("_"));
  return (
    <ul className="space-y-3">
      {keys.map((k) => {
        const c = breakdown[k];
        const before = compare?.[k];
        const pct = c.value === null ? 0 : Math.round(c.value * 100);
        return (
          <li key={k}>
            <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
              <span className="font-medium">{COMPONENT_LABELS[k] ?? k}</span>
              <span className="tabular-nums text-zinc-500">
                {c.points === null ? "n/a" : `${c.points} / ${c.weight}`}
                {before && before.points !== null && c.points !== null && c.points !== before.points && (
                  <span className={c.points > before.points ? "ml-1 text-emerald-600" : "ml-1 text-rose-600"}>
                    ({c.points > before.points ? "+" : ""}
                    {(c.points - before.points).toFixed(1)})
                  </span>
                )}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
              <div className={`h-full rounded-full ${c.value === null ? "" : "bg-indigo-500"}`} style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-1 text-xs text-zinc-500">{c.detail}</p>
          </li>
        );
      })}
    </ul>
  );
}

const GAP_META: Record<keyof Gaps, { title: string; tone: string; hint: string }> = {
  gap: { title: "True gaps", tone: "border-rose-300 dark:border-rose-900", hint: "No evidence. Never added; disclose if asked." },
  adjacent: { title: "Adjacent", tone: "border-amber-300 dark:border-amber-900", hint: "Related evidence. Frame honestly in a cover letter." },
  hidden: { title: "Covered but hidden", tone: "border-sky-300 dark:border-sky-900", hint: "In your pool, not on this resume. Tailoring adds these." },
  shown: { title: "Covered and shown", tone: "border-emerald-300 dark:border-emerald-900", hint: "Already on your resume." },
};

function GapList({ items }: { items: GapItem[] }) {
  if (!items.length) return <p className="text-xs text-zinc-500">None</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((g) => (
        <li
          key={g.item}
          title={[g.evidence.length ? `Evidence: ${g.evidence.join(", ")}` : "", g.note].filter(Boolean).join("\n")}
          className={`chip border bg-white dark:bg-zinc-900 ${g.required ? "border-zinc-400 font-semibold dark:border-zinc-500" : "border-zinc-200 font-normal dark:border-zinc-700"}`}
        >
          {g.item}
          {g.kind === "soft" && <span className="text-[10px] text-zinc-400">soft</span>}
        </li>
      ))}
    </ul>
  );
}

export function GapsPanel({ gaps }: { gaps: Gaps }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {(Object.keys(GAP_META) as (keyof Gaps)[]).map((k) => (
        <div key={k} className={`rounded-lg border-l-4 bg-zinc-50 p-3 dark:bg-zinc-950 ${GAP_META[k].tone}`}>
          <div className="mb-1 flex items-baseline justify-between">
            <h3 className="text-sm font-semibold">{GAP_META[k].title}</h3>
            <span className="text-xs text-zinc-500">{gaps[k].length}</span>
          </div>
          <p className="mb-2 text-xs text-zinc-500">{GAP_META[k].hint}</p>
          <GapList items={gaps[k]} />
        </div>
      ))}
      <p className="text-xs text-zinc-500 sm:col-span-2">Bold = must-have. Hover a skill to see your evidence.</p>
    </div>
  );
}

export function FlagsList({ flags }: { flags: Flag[] }) {
  if (!flags.length) return <p className="text-sm text-zinc-500">No knockout risks found.</p>;
  return (
    <ul className="space-y-2">
      {flags.map((f, i) => (
        <li key={i} className="flex gap-2 text-sm">
          <SeverityChip severity={f.severity} />
          <div>
            <p>{f.message}</p>
            {f.evidence && <p className="mt-0.5 text-xs italic text-zinc-500">{f.evidence}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function SkillsLines({ skills, highlight }: { skills: Record<string, string[]>; highlight?: Set<string> }) {
  return (
    <div className="space-y-1 text-sm">
      {Object.entries(skills).map(([label, items]) => (
        <p key={label}>
          <span className="font-semibold">{label}: </span>
          {items.map((it, i) => (
            <span key={it}>
              <span className={highlight && !highlight.has(it) ? "rounded bg-emerald-100 px-0.5 dark:bg-emerald-950" : ""}>{it}</span>
              {i < items.length - 1 ? ", " : ""}
            </span>
          ))}
        </p>
      ))}
    </div>
  );
}

export function TailorPanel({ job, onDone }: { job: JobDetail; onDone?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TailorResult | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.tailor(job.id));
      onDone?.();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  async function download(fmt: "pdf" | "docx", id: number) {
    try {
      await api.download(id, fmt);
    } catch (e) {
      setError(errMsg(e));
    }
  }

  const latest = result?.version ?? job.tailored_versions[0];
  const masterSkills = new Set(Object.values(result?.master.skills ?? {}).flat());

  return (
    <Section
      title="Tailor Objective and Skills"
      right={
        <button className="btn btn-primary" onClick={run} disabled={busy}>
          {busy ? <Spinner /> : null}
          {latest ? "Re-tailor" : "Tailor for this job"}
        </button>
      }
    >
      <p className="mb-3 text-xs text-zinc-500">
        Only Objective and Skills change. Projects, experience and education stay locked word-for-word, and every draft passes the rule validator before a file is built.
      </p>
      <ErrorBox error={error} />
      {result && (
        <div className="mb-4 flex flex-wrap items-center gap-4">
          <ScoreBadge score={result.before.total} label="before" />
          <span className="text-zinc-400">→</span>
          <ScoreBadge score={result.after.total} label="after" />
          <span className="text-xs text-zinc-500">Drafted by {result.source === "claude" ? "Claude, validated" : "the rule-based template"}.</span>
        </div>
      )}
      {latest && (
        <div className="space-y-4">
          <div>
            <span className="label">Objective</span>
            <p className="text-sm">{latest.objective}</p>
            {result && result.master.objective !== latest.objective && (
              <details className="mt-1 text-xs text-zinc-500">
                <summary className="cursor-pointer">Master objective</summary>
                <p className="mt-1">{result.master.objective}</p>
              </details>
            )}
          </div>
          <div>
            <span className="label">Skills {result && <span className="normal-case tracking-normal">(green = surfaced from your pool)</span>}</span>
            <SkillsLines skills={latest.skills} highlight={result ? masterSkills : undefined} />
          </div>
          {latest.validation && (
            <div className="text-sm">
              {latest.validation.ok ? (
                <p className="text-emerald-700 dark:text-emerald-400">Validator passed: no new skills, no em dashes, locked text intact, order kept.</p>
              ) : (
                <ul className="space-y-1 text-rose-700 dark:text-rose-400">
                  {latest.validation.errors.map((e, i) => (
                    <li key={i}>✗ {e.message}</li>
                  ))}
                </ul>
              )}
              {latest.validation.warnings?.map((w, i) => (
                <p key={i} className="text-amber-700 dark:text-amber-400">! {w.message}</p>
              ))}
            </div>
          )}
          {latest.validation?.ok && (
            <div className="flex flex-wrap gap-2">
              {latest.has_pdf && (
                <button className="btn btn-primary" onClick={() => download("pdf", latest.id)}>
                  Download PDF
                </button>
              )}
              <button className="btn btn-ghost" onClick={() => download("docx", latest.id)}>
                Download DOCX
              </button>
            </div>
          )}
          {result && result.gaps_to_disclose.length > 0 && (
            <div className="rounded-lg bg-rose-50 p-3 text-sm dark:bg-rose-950/40">
              <p className="font-medium">Must-haves you lack (not added; be ready to address them):</p>
              <p className="mt-1">{result.gaps_to_disclose.map((g) => g.item).join(", ")}</p>
            </div>
          )}
          {result && result.adjacent.length > 0 && (
            <div className="rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
              <p className="font-medium">Cover-letter angles (related evidence):</p>
              <ul className="mt-1 list-disc pl-5">
                {result.adjacent.map((g) => (
                  <li key={g.item}>
                    {g.item}: {g.note.replace(/ Frame honestly.*$/, "")}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

function TrackButton({ job, onChange }: { job: JobDetail; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (job.application_status)
    return (
      <Link href="/tracker" className="chip bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300">
        In tracker: {job.application_status}
      </Link>
    );
  return (
    <span className="inline-flex items-center gap-2">
      <button
        className="btn btn-ghost"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const a = await api.createApplication({ job_id: job.id, status: "saved", resume_version_id: job.tailored_versions[0]?.id ?? null });
            setMsg(a.warnings?.[0] ?? null);
            onChange();
          } catch (e) {
            setMsg(errMsg(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        Save to tracker
      </button>
      {msg && <span className="text-xs text-amber-600">{msg}</span>}
    </span>
  );
}

export function JobAnalysis({ job, onRefresh }: { job: JobDetail; onRefresh: () => void }) {
  const blocked = job.flags.some((f) => f.severity === "block");
  return (
    <div className="space-y-4">
      <div className="card flex flex-col gap-4 sm:flex-row sm:items-start">
        <div className="flex gap-3">
          <ScoreBadge score={job.score} label="now" size="lg" />
          {job.potential !== null && <ScoreBadge score={job.potential} label="tailored" size="lg" />}
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold leading-tight">{job.title || "Untitled role"}</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {[job.company, job.location, job.remote ? "Remote" : null, fmtSalary(job.salary)].filter(Boolean).join(" · ")}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
            {blocked && <SeverityChip severity="block">knockout risk</SeverityChip>}
            {!job.active && <span className="chip bg-zinc-200 dark:bg-zinc-800">closed</span>}
            <span>{job.source}</span>
            {job.posted_at && <span>posted {fmtDate(job.posted_at)}</span>}
            {job.url && (
              <a href={job.url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
                Open posting ↗
              </a>
            )}
            {job.source === "adzuna" && <span>Jobs by Adzuna</span>}
          </div>
          {job.snippet_only && (
            <p className="mt-2 text-xs text-amber-600">This source only provides a snippet. Paste the full JD on the Score page for an accurate score.</p>
          )}
          <p className="mt-2 text-xs text-zinc-500">Estimates, not a real ATS result. Knockout risks are shown separately and never averaged in.</p>
        </div>
        <TrackButton job={job} onChange={onRefresh} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Knockout risks">
          <FlagsList flags={job.flags} />
        </Section>
        {job.breakdown && (
          <Section title="Score breakdown">
            <BreakdownBars breakdown={job.breakdown} />
          </Section>
        )}
      </div>

      {job.gaps && (
        <Section title="Requirements vs your evidence">
          <GapsPanel gaps={job.gaps} />
        </Section>
      )}

      <TailorPanel job={job} onDone={onRefresh} />

      <Section title="Job description">
        <details>
          <summary className="cursor-pointer text-sm text-zinc-500">Show full text</summary>
          <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm">{job.jd_text}</pre>
        </details>
      </Section>
    </div>
  );
}
