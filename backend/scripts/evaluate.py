"""Score the golden set and compare against your own verdicts.

Usage: python scripts/evaluate.py [--llm] [--dir data/golden]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from app.engine.eligibility import check_all  # noqa: E402
from app.engine.extract import extract  # noqa: E402
from app.engine.scorer import score  # noqa: E402
from app.engine.tailor import tailor  # noqa: E402
from app.facts import get_facts, render_resume_text  # noqa: E402

RANK = {"skip": 0, "maybe": 1, "apply": 2}


def band(total: float, blocked: bool, apply_at: float, skip_below: float) -> str:
    if blocked or total < skip_below:
        return "skip"
    return "apply" if total >= apply_at else "maybe"


def spearman(xs: list[float], ys: list[float]) -> float | None:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parent.parent / "data" / "golden"))
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--apply-at", type=float, default=70)
    ap.add_argument("--skip-below", type=float, default=55)
    ap.add_argument("--master-only", action="store_true", help="score the untailored master resume")
    args = ap.parse_args()

    facts = get_facts()
    resume = render_resume_text(facts)
    rows = []
    flag_hits = flag_total = 0
    for path in sorted(Path(args.dir).glob("*.yaml")):
        g = yaml.safe_load(path.read_text())
        ex = extract(g["jd_text"], title=g.get("title", ""), company=g.get("company"), location=g.get("location"), use_llm=args.llm)
        s = score(ex, resume, g["jd_text"], facts)
        if not args.master_only:
            # Judge on the score after tailoring: hidden pool skills are yours to show.
            t = tailor(ex, g["jd_text"], facts, use_llm=False)
            if t.validation.ok:
                s = score(ex, render_resume_text(facts, t.objective, t.skills), g["jd_text"], facts)
        flags = check_all(g["jd_text"], ex, facts)
        blocking = {f.type for f in flags if f.severity == "block"}
        expected = set(g.get("expected_flags") or [])
        flag_hits += len(expected & blocking)
        flag_total += len(expected)
        predicted = band(s.total, bool(blocking), args.apply_at, args.skip_below)
        rows.append((path.name, g["verdict"], predicted, s.total, sorted(blocking), sorted(expected - blocking)))

    if not rows:
        print("No golden files found.")
        return
    print(f"{'file':34} {'you':6} {'app':6} {'score':>6}  blocking flags / missed expected flags")
    for name, verdict, pred, total, blocking, missed in rows:
        mark = " " if verdict == pred else "x"
        print(f"{mark} {name:32} {verdict:6} {pred:6} {total:6.1f}  {', '.join(blocking) or '-'}{'  MISSED: ' + ', '.join(missed) if missed else ''}")
    agree = sum(1 for r in rows if r[1] == r[2]) / len(rows)
    rho = spearman([RANK[r[1]] for r in rows], [r[3] - (100 if r[4] else 0) for r in rows])
    print(f"\nVerdict agreement: {agree:.0%} on {len(rows)} JDs")
    print(f"Rank correlation (Spearman): {rho:.2f}" if rho is not None else "Rank correlation: need 3+ JDs")
    print(f"Expected flag recall: {flag_hits}/{flag_total}" if flag_total else "Expected flag recall: n/a")
    if len(rows) < 30:
        print(f"\nGate needs 30+ labeled JDs; you have {len(rows)}.")


if __name__ == "__main__":
    main()
