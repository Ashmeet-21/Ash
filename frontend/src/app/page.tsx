"use client";

import { useState } from "react";

import { JobAnalysis } from "@/components/JobAnalysis";
import { ErrorBox, Spinner, errMsg } from "@/components/ui";
import { api, type JobDetail } from "@/lib/api";

export default function ScorePage() {
  const [mode, setMode] = useState<"text" | "link">("text");
  const [jd, setJd] = useState("");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = mode === "text" ? { jd_text: jd, url: url || undefined } : { url };
      setJob(await api.score({ ...body, title: title || undefined, company: company || undefined, location: location || undefined }));
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    if (job) setJob(await api.job(job.id));
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Score a job</h1>
        <p className="text-sm text-zinc-500">Paste a job description or a link. You get a match score, the gaps, knockout risks and a tailored resume.</p>
      </div>

      <form onSubmit={submit} className="card space-y-4">
        <div className="inline-flex rounded-lg border border-zinc-300 p-0.5 text-sm dark:border-zinc-700">
          {(["text", "link"] as const).map((m) => (
            <button
              type="button"
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1 ${mode === m ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900" : ""}`}
            >
              {m === "text" ? "Paste JD" : "Job link"}
            </button>
          ))}
        </div>

        {mode === "text" ? (
          <div>
            <label className="label" htmlFor="jd">
              Job description
            </label>
            <textarea id="jd" className="input min-h-56 font-mono text-xs" value={jd} onChange={(e) => setJd(e.target.value)} placeholder="Paste the full posting text..." required />
          </div>
        ) : (
          <div>
            <label className="label" htmlFor="url">
              Posting URL
            </label>
            <input id="url" className="input" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://boards.greenhouse.io/company/jobs/123" required />
            <p className="mt-1 text-xs text-zinc-500">
              Greenhouse, Lever and Ashby links use their public APIs. LinkedIn, Indeed, Naukri and Bayt have no open route: paste the text instead.
            </p>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label className="label" htmlFor="title">
              Title (optional)
            </label>
            <input id="title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Junior SOC Analyst" />
          </div>
          <div>
            <label className="label" htmlFor="company">
              Company
            </label>
            <input id="company" className="input" value={company} onChange={(e) => setCompany(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="location">
              Location
            </label>
            <input id="location" className="input" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Vancouver, BC" />
          </div>
        </div>
        {mode === "text" && (
          <div>
            <label className="label" htmlFor="srcurl">
              Posting link (optional, for your records)
            </label>
            <input id="srcurl" className="input" type="url" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
        )}

        <div className="flex items-center gap-3">
          <button className="btn btn-primary" disabled={busy}>
            {busy && <Spinner />}
            Score it
          </button>
          {busy && <span className="text-xs text-zinc-500">Extracting requirements and scoring...</span>}
        </div>
        <ErrorBox error={error} />
      </form>

      {job && <JobAnalysis job={job} onRefresh={refresh} />}
    </div>
  );
}
