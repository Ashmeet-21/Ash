"use client";

import { useState } from "react";

import { Empty, ErrorBox, Section, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/hooks";

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

export default function InsightsPage() {
  const [minScore, setMinScore] = useState(40);
  const { data: summary, error: summaryError } = useLoad(() => api.summary(), []);
  const { data: demandData, error: demandError, loading } = useLoad(() => api.skillDemand(minScore), [minScore]);
  const demand = loading ? null : demandData;
  const error = summaryError ?? demandError;

  const missing = demand?.filter((d) => !d.have) ?? [];
  const max = Math.max(1, ...missing.map((d) => d.jobs));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
        <p className="text-sm text-zinc-500">What the jobs you want keep asking for.</p>
      </div>
      <ErrorBox error={error} />
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Active jobs" value={summary.active_jobs} />
          <Stat label="Strong matches" value={summary.strong_matches} />
          <Stat label="Average score" value={summary.avg_score ?? "-"} />
          <Stat label="Applied" value={(summary.applications.applied ?? 0) + (summary.applications.interview ?? 0) + (summary.applications.offer ?? 0)} />
        </div>
      )}
      <Section
        title="Skills you lack, ranked by demand"
        right={
          <label className="flex items-center gap-2 text-xs text-zinc-500">
            jobs scoring ≥ {minScore}
            <input type="range" min={0} max={80} step={5} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} />
          </label>
        }
      >
        {demand === null && <Spinner />}
        {demand && missing.length === 0 && <Empty>No missing skills yet. Score or fetch more jobs.</Empty>}
        <ul className="space-y-2">
          {missing.slice(0, 25).map((d) => (
            <li key={d.skill} className="text-sm">
              <div className="mb-0.5 flex justify-between">
                <span className="font-medium">{d.skill}</span>
                <span className="text-xs text-zinc-500">
                  {d.jobs} jobs · must-have in {d.required_in}
                </span>
              </div>
              <div className="h-2 rounded-full bg-zinc-200 dark:bg-zinc-800">
                <div className="h-full rounded-full bg-rose-400" style={{ width: `${(d.jobs / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-zinc-500">Learning targets: build a small project that evidences one of these, then add it to your skill pool.</p>
      </Section>
    </div>
  );
}
