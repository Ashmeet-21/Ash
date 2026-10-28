"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { JobAnalysis } from "@/components/JobAnalysis";
import { ErrorBox, Spinner, errMsg } from "@/components/ui";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/hooks";

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const { data: job, error: loadError, reload, setData: setJob } = useLoad(() => api.job(Number(id)), [id]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Link href="/jobs" className="text-sm text-indigo-600 hover:underline">
          ← Feed
        </Link>
        {job && (
          <button
            className="btn btn-ghost"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                setJob(await api.rescore(job.id));
              } catch (e) {
                setError(errMsg(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy && <Spinner />}
            Re-score
          </button>
        )}
      </div>
      <ErrorBox error={error ?? loadError} />
      {!job && !loadError && <Spinner label="Loading..." />}
      {job && <JobAnalysis job={job} onRefresh={reload} />}
    </div>
  );
}
