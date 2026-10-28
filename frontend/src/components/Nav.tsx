"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Score" },
  { href: "/jobs", label: "Feed" },
  { href: "/tracker", label: "Tracker" },
  { href: "/resume", label: "Resume" },
  { href: "/insights", label: "Insights" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/85 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/85">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <Link href="/" className="shrink-0 text-base font-semibold tracking-tight">
          Job<span className="text-indigo-600">Match</span>
        </Link>
        <nav className="-mx-1 flex min-w-0 gap-1 overflow-x-auto">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm ${
                active(l.href) ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900" : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              }`}
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
