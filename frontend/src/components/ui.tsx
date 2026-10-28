import type { Severity } from "@/lib/api";

export function scoreTone(score: number | null | undefined): string {
  if (score === null || score === undefined) return "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  if (score >= 70) return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300";
  if (score >= 55) return "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300";
  return "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300";
}

export function ScoreBadge({ score, label, size = "md" }: { score: number | null | undefined; label?: string; size?: "md" | "lg" }) {
  const big = size === "lg";
  return (
    <div className={`flex flex-col items-center justify-center rounded-xl ${scoreTone(score)} ${big ? "h-20 w-20" : "h-12 w-12"}`}>
      <span className={`font-semibold tabular-nums ${big ? "text-2xl" : "text-base"}`}>{score === null || score === undefined ? "-" : Math.round(score)}</span>
      {label && <span className="text-[10px] uppercase tracking-wide opacity-80">{label}</span>}
    </div>
  );
}

const SEV: Record<Severity, string> = {
  block: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  warn: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  info: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
};

export function SeverityChip({ severity, children }: { severity: Severity; children?: React.ReactNode }) {
  return <span className={`chip shrink-0 self-start ${SEV[severity]}`}>{children ?? severity}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-zinc-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-indigo-600" />
      {label}
    </span>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">{error}</div>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700">{children}</div>;
}

export function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="card">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function fmtSalary(s: { min: number | null; max: number | null; currency: string | null } | null): string {
  if (!s || !s.min) return "";
  const f = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n));
  return `${s.currency ?? ""} ${f(s.min)}${s.max && s.max !== s.min ? `-${f(s.max)}` : ""}`.trim();
}

export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
