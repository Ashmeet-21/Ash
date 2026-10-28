// Typed client for the JobMatch API.

export type Severity = "block" | "warn" | "info";

export interface Component {
  weight: number;
  value: number | null;
  points: number | null;
  detail: string;
}

export type Breakdown = Record<string, Component> & { _meta?: { potential?: number } };

export interface GapItem {
  item: string;
  kind: string;
  required: boolean;
  status: "shown" | "hidden" | "adjacent" | "gap";
  evidence: string[];
  note: string;
}

export interface Gaps {
  shown: GapItem[];
  hidden: GapItem[];
  adjacent: GapItem[];
  gap: GapItem[];
}

export interface Flag {
  type: string;
  severity: Severity;
  message: string;
  evidence: string;
}

export interface Validation {
  ok: boolean;
  errors: { rule: string; message: string }[];
  warnings: { rule: string; message: string }[];
  source?: string;
  attempts?: number;
  role?: string;
  areas?: string[];
  tools?: string[];
}

export interface ResumeVersion {
  id: number;
  job_id: number | null;
  objective: string;
  skills: Record<string, string[]>;
  validation: Validation | null;
  created_at: string;
  score: number | null;
  has_pdf: boolean;
}

export interface JobSummary {
  id: number;
  title: string;
  company: string | null;
  location: string | null;
  remote: boolean;
  source: string;
  url: string | null;
  posted_at: string | null;
  first_seen_at: string;
  active: boolean;
  regions: string[];
  role_type: "co-op" | "new-grad" | "other";
  salary: { min: number | null; max: number | null; currency: string | null } | null;
  score: number | null;
  potential: number | null;
  flag_counts: Record<Severity, number>;
  application_status: string | null;
}

export interface JobDetail extends JobSummary {
  jd_text: string;
  extraction: {
    seniority: string | null;
    min_years: number | null;
    education: { required: boolean; level: string | null; fields: string[] } | null;
    sources: string[] | null;
  };
  requirements: { item: string; kind: string; required: boolean }[];
  breakdown: Breakdown | null;
  gaps: Gaps | null;
  flags: Flag[];
  tailored_versions: ResumeVersion[];
  snippet_only: boolean;
}

export interface TailorResult {
  version: ResumeVersion;
  before: { total: number; breakdown: Breakdown };
  after: { total: number; breakdown: Breakdown };
  master: { objective: string; skills: Record<string, string[]> };
  gaps_to_disclose: GapItem[];
  adjacent: GapItem[];
  source: "template" | "claude";
}

export interface Application {
  id: number;
  job_id: number;
  status: AppStatus;
  resume_version_id: number | null;
  applied_at: string | null;
  deadline: string | null;
  notes: string | null;
  updated_at: string;
  job: { title: string; company: string | null; location: string | null; url: string | null; active: boolean };
  score: number | null;
  warnings?: string[];
}

export const APP_STATUSES = ["saved", "applied", "interview", "offer", "rejected", "withdrawn"] as const;
export type AppStatus = (typeof APP_STATUSES)[number];

export interface ParseCheck {
  file_type: string;
  pages: number;
  text: string;
  checks: { key: string; passed: boolean; severity: "error" | "warn" | "info"; message: string }[];
  detected_sections: string[];
  contact: { email: string | null; phone: string | null };
  format_score: number;
}

export interface Profile {
  name: string;
  graduation: string;
  open_to_regions: string[];
  target_titles: string[];
  skill_pool: { skill: string; evidence: string[] }[];
  master: { id: number; objective: string; skills: Record<string, string[]> };
  parse_check: Omit<ParseCheck, "text"> | null;
  regions: Record<string, string>;
  llm: boolean;
}

export interface IngestSummary {
  fetched: number;
  kept: number;
  new: number;
  updated: number;
  duplicates: number;
  closed: number;
  errors: string[];
  new_matches: { id: number; title: string; company: string | null; score: number; potential: number }[];
}

const KEY_URL = "jobmatch.apiUrl";
const KEY_TOKEN = "jobmatch.token";

function read(key: string): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function getApiUrl(): string {
  return (read(KEY_URL) || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
}

export function getToken(): string {
  return read(KEY_TOKEN) || "";
}

export function saveConnection(url: string, token: string) {
  try {
    window.localStorage.setItem(KEY_URL, url);
    window.localStorage.setItem(KEY_TOKEN, token);
  } catch {
    /* storage unavailable: settings last for this page view only */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${getApiUrl()}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${getApiUrl()}. Is the backend running?`);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<{ ok: boolean; llm: boolean }>("/health"),
  profile: () => request<Profile>("/profile"),
  score: (body: { jd_text?: string; url?: string; title?: string; company?: string; location?: string }) =>
    request<JobDetail>("/jobs/score", { method: "POST", body: JSON.stringify(body) }),
  jobs: (params: Record<string, string | number | boolean | undefined>) =>
    request<{ total: number; items: JobSummary[] }>(`/jobs${qs(params)}`),
  job: (id: number) => request<JobDetail>(`/jobs/${id}`),
  rescore: (id: number) => request<JobDetail>(`/jobs/${id}/rescore`, { method: "POST" }),
  deleteJob: (id: number) => request<{ ok: boolean }>(`/jobs/${id}`, { method: "DELETE" }),
  ingest: () => request<IngestSummary>("/jobs/ingest", { method: "POST" }),
  alerts: (hours = 24) => request<JobSummary[]>(`/alerts${qs({ since_hours: hours })}`),
  tailor: (id: number) => request<TailorResult>(`/tailor/${id}`, { method: "POST" }),
  downloadUrl: (versionId: number, fmt: "pdf" | "docx") => `${getApiUrl()}/resume-versions/${versionId}/download?fmt=${fmt}`,
  download: async (versionId: number, fmt: "pdf" | "docx") => {
    const headers: HeadersInit = getToken() ? { Authorization: `Bearer ${getToken()}` } : {};
    const res = await fetch(api.downloadUrl(versionId, fmt), { headers });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({ detail: res.statusText }))).detail);
    const blob = await res.blob();
    const name = /filename="?([^"]+)"?/.exec(res.headers.get("Content-Disposition") || "")?.[1] || `resume.${fmt}`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  },
  parseCheck: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<ParseCheck>("/resume/parse-check", { method: "POST", body: fd });
  },
  applications: () => request<Application[]>("/applications"),
  createApplication: (body: { job_id: number; status?: AppStatus; resume_version_id?: number | null }) =>
    request<Application>("/applications", { method: "POST", body: JSON.stringify(body) }),
  updateApplication: (id: number, body: Partial<Pick<Application, "status" | "deadline" | "notes" | "resume_version_id" | "applied_at">>) =>
    request<Application>(`/applications/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteApplication: (id: number) => request<{ ok: boolean }>(`/applications/${id}`, { method: "DELETE" }),
  skillDemand: (minScore = 0) => request<{ skill: string; jobs: number; required_in: number; have: boolean }[]>(`/insights/skills${qs({ min_score: minScore })}`),
  summary: () =>
    request<{ active_jobs: number; strong_matches: number; avg_score: number | null; applications: Record<string, number> }>("/insights/summary"),
};
