"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Empty, ErrorBox, ScoreBadge, Spinner, errMsg, fmtDate } from "@/components/ui";
import { APP_STATUSES, api, type AppStatus, type Application } from "@/lib/api";
import { useLoad } from "@/lib/hooks";

const TONE: Record<AppStatus, string> = {
  saved: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  applied: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  interview: "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300",
  offer: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  rejected: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  withdrawn: "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
};

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
}

function Row({ a, onChanged, onDeleted }: { a: Application; onChanged: (a: Application) => void; onDeleted: () => void }) {
  const [notes, setNotes] = useState(a.notes ?? "");
  const [warning, setWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function patch(body: Parameters<typeof api.updateApplication>[1]) {
    setError(null);
    try {
      const updated = await api.updateApplication(a.id, body);
      setWarning(updated.warnings?.[0] ?? null);
      onChanged(updated);
    } catch (e) {
      setError(errMsg(e));
    }
  }

  const due = daysUntil(a.deadline);
  return (
    <li className="card space-y-3">
      <div className="flex items-start gap-3">
        <ScoreBadge score={a.score} />
        <div className="min-w-0 flex-1">
          <Link href={`/jobs/${a.job_id}`} className="font-medium hover:underline">
            {a.job.title}
          </Link>
          <p className="text-sm text-zinc-500">{[a.job.company, a.job.location].filter(Boolean).join(" · ")}</p>
          <p className="mt-1 text-xs text-zinc-500">
            {a.applied_at ? `Applied ${fmtDate(a.applied_at)}` : "Not applied yet"}
            {!a.job.active && " · posting closed"}
            {a.resume_version_id && " · tailored resume attached"}
          </p>
        </div>
        <select
          aria-label="Status"
          className={`chip cursor-pointer border-0 py-1 ${TONE[a.status]}`}
          value={a.status}
          onChange={(e) => patch({ status: e.target.value as AppStatus })}
        >
          {APP_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-3 sm:grid-cols-[180px_1fr]">
        <div>
          <label className="label">Deadline / follow-up</label>
          <input
            type="date"
            className="input"
            value={a.deadline ? a.deadline.slice(0, 10) : ""}
            onChange={(e) => patch({ deadline: e.target.value ? new Date(e.target.value + "T23:59:00").toISOString() : null })}
          />
          {due !== null && (
            <p className={`mt-1 text-xs ${due < 0 ? "text-rose-600" : due <= 3 ? "text-amber-600" : "text-zinc-500"}`}>
              {due < 0 ? `${-due} days overdue` : due === 0 ? "Due today" : `${due} days left`}
            </p>
          )}
        </div>
        <div>
          <label className="label">Notes</label>
          <textarea className="input min-h-16" value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (a.notes ?? "") && patch({ notes })} />
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-xs text-amber-600">{warning}</span>
        <button
          className="text-xs text-zinc-500 hover:text-rose-600"
          onClick={async () => {
            if (!confirm("Remove this application from the tracker?")) return;
            await api.deleteApplication(a.id);
            onDeleted();
          }}
        >
          Remove
        </button>
      </div>
      <ErrorBox error={error} />
    </li>
  );
}

export default function TrackerPage() {
  const { data: apps, error, setData } = useLoad(() => api.applications(), []);
  const [status, setStatus] = useState<AppStatus | "">("");
  const setApps = (fn: (xs: Application[]) => Application[]) => apps && setData(fn(apps));

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of apps ?? []) c[a.status] = (c[a.status] ?? 0) + 1;
    return c;
  }, [apps]);

  const shown = (apps ?? []).filter((a) => !status || a.status === status);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Application tracker</h1>
        <p className="text-sm text-zinc-500">Save jobs from the feed, then move them through applied, interview and offer.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className={`chip px-3 py-1 ${status === "" ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900" : "bg-zinc-100 dark:bg-zinc-800"}`} onClick={() => setStatus("")}>
          All {apps?.length ?? 0}
        </button>
        {APP_STATUSES.map((s) => (
          <button key={s} className={`chip px-3 py-1 ${status === s ? "ring-2 ring-indigo-500" : ""} ${TONE[s]}`} onClick={() => setStatus(s)}>
            {s} {counts[s] ?? 0}
          </button>
        ))}
      </div>
      <ErrorBox error={error} />
      {apps === null && <Spinner label="Loading..." />}
      {apps && shown.length === 0 && <Empty>Nothing here yet. Open a job and press “Save to tracker”.</Empty>}
      <ul className="space-y-3">
        {shown.map((a) => (
          <Row
            key={a.id}
            a={a}
            onChanged={(u) => setApps((xs) => xs.map((x) => (x.id === u.id ? { ...x, ...u } : x)))}
            onDeleted={() => setApps((xs) => xs.filter((x) => x.id !== a.id))}
          />
        ))}
      </ul>
    </div>
  );
}
