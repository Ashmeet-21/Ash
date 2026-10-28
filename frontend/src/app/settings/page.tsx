"use client";

import { useState } from "react";

import { ErrorBox, Section, Spinner, errMsg } from "@/components/ui";
import { api, getApiUrl, getToken, saveConnection } from "@/lib/api";
import { useHydrated } from "@/lib/hooks";

export default function SettingsPage() {
  // Values live in browser storage, so render the form only after hydration.
  return useHydrated() ? <SettingsForm /> : <Spinner label="Loading..." />;
}

function SettingsForm() {
  const [url, setUrl] = useState(getApiUrl);
  const [token, setToken] = useState(getToken);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function test() {
    setBusy(true);
    setError(null);
    setStatus(null);
    saveConnection(url, token);
    try {
      const h = await api.health();
      await api.profile(); // checks the token too
      setStatus(`Connected. Claude ${h.llm ? "is enabled" : "is off (rule-based extraction and template tailoring)"}.`);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <Section title="Backend connection">
        <div className="space-y-3">
          <div>
            <label className="label" htmlFor="url">
              API URL
            </label>
            <input id="url" className="input" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="token">
              API token (only if JOBMATCH_API_TOKEN is set)
            </label>
            <input id="token" className="input" type="password" value={token} onChange={(e) => setToken(e.target.value)} />
          </div>
          <button className="btn btn-primary" onClick={test} disabled={busy}>
            {busy && <Spinner />}
            Save and test
          </button>
          {status && <p className="text-sm text-emerald-700 dark:text-emerald-400">{status}</p>}
          <ErrorBox error={error} />
          <p className="text-xs text-zinc-500">Stored in this browser only.</p>
        </div>
      </Section>
    </div>
  );
}
