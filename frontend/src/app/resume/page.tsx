"use client";

import { useEffect, useState } from "react";

import { ErrorBox, ScoreBadge, Section, Spinner, errMsg } from "@/components/ui";
import { api, type ParseCheck, type Profile } from "@/lib/api";

const SEV_ICON = { error: "✗", warn: "!", info: "i" } as const;

export default function ResumePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [result, setResult] = useState<ParseCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.profile().then(setProfile).catch((e) => setError(errMsg(e)));
  }, []);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.parseCheck(file));
      setProfile(await api.profile());
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  const checks = result?.checks ?? profile?.parse_check?.checks ?? [];
  const fmt = result?.format_score ?? profile?.parse_check?.format_score;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Resume</h1>
        <p className="text-sm text-zinc-500">Your master resume, evidenced skill pool and ATS parse check.</p>
      </div>
      <ErrorBox error={error} />

      <Section title="ATS parse check" right={fmt !== undefined && fmt !== null ? <ScoreBadge score={fmt * 100} label="format" /> : null}>
        <p className="mb-3 text-sm text-zinc-500">
          Upload the PDF (or DOCX) you actually send. JobMatch shows what a basic parser extracts and flags columns, tables, images, text boxes and contact details hidden in headers. The result feeds the format part of every score.
        </p>
        <label className="btn btn-primary cursor-pointer">
          {busy ? <Spinner /> : null}
          Upload resume
          <input type="file" accept=".pdf,.docx" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </label>
        {checks.length > 0 && (
          <ul className="mt-4 space-y-1.5 text-sm">
            {checks.map((c) => (
              <li key={c.key} className="flex gap-2">
                <span className={c.passed ? "text-emerald-600" : c.severity === "error" ? "text-rose-600" : "text-amber-600"}>{c.passed ? "✓" : SEV_ICON[c.severity]}</span>
                <span>{c.message}</span>
              </li>
            ))}
          </ul>
        )}
        {result && (
          <details className="mt-3">
            <summary className="cursor-pointer text-sm text-zinc-500">What the parser extracted ({result.text.length} characters)</summary>
            <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-zinc-100 p-3 text-xs dark:bg-zinc-950">{result.text}</pre>
          </details>
        )}
      </Section>

      {profile && (
        <>
          <Section title="Master resume (tailorable sections)">
            <span className="label">Objective</span>
            <p className="mb-3 text-sm">{profile.master.objective}</p>
            <span className="label">Skills</span>
            {Object.entries(profile.master.skills).map(([label, items]) => (
              <p key={label} className="text-sm">
                <b>{label}:</b> {items.join(", ")}
              </p>
            ))}
            <p className="mt-3 text-xs text-zinc-500">
              Edit <code>backend/data/facts.yaml</code> to change your master resume, skill pool or locked sections. Projects and experience are never rewritten.
            </p>
          </Section>

          <Section title={`Evidenced skill pool (${profile.skill_pool.length})`}>
            <p className="mb-3 text-xs text-zinc-500">The only skills the tailor may use. A JD skill outside this list is reported as a gap, never added.</p>
            <ul className="flex flex-wrap gap-1.5">
              {profile.skill_pool.map((s) => (
                <li key={s.skill} title={`Evidence: ${s.evidence.join(", ")}`} className="chip border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
                  {s.skill}
                </li>
              ))}
            </ul>
          </Section>
        </>
      )}
    </div>
  );
}
