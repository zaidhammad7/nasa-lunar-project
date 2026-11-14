"""Run every validation suite in one go and publish a single summary.

    python tests/run_all.py            (add --quick to skip the slow NASA benchmark)

Suites
  tests/test_all.py              100 data / physics / model / API / browser-parity cases
  tests/test_edge_cases.py       boundary limits, malformed input, mode consistency, tower propagation, front-end error handling
  tests/test_verdict_rules.py    a taller mast never downgrades a verdict; fixed 5.0 deg Optimal slope; tower / battery map
  src/app/api_selftest.py        every API endpoint against independently recomputed values
  src/analysis/test_tower_limit.py   tower-height physics (1-150 m)
  src/analysis/nasa_benchmark.py     checks against NASA LOLA / JPL Horizons reference data

Prints a table, lists every failing check with its detail, writes outputs/test_summary.json (served by GET /api/validation and
shown as the validation badge in the dashboard header) and exits with code 1 if anything failed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
SUITES = [  # (name, script, JSON report written by the script or None)
    ("Data & system (100 cases)", "tests/test_all.py", "test_all_report.json"),
    ("Edge cases & error handling", "tests/test_edge_cases.py", "test_edge_cases_report.json"),
    ("Verdict rules (mast, slope, map)", "tests/test_verdict_rules.py", "test_verdict_rules_report.json"),
    ("API self-test", "src/app/api_selftest.py", "api_selftest_report.json"),
    ("Tower physics", "src/analysis/test_tower_limit.py", None),
    ("NASA / JPL benchmark", "src/analysis/nasa_benchmark.py", "nasa_benchmark.json"),
]


def _from_report(path: Path) -> tuple[int, int, list[dict]]:
    """(passed, total, failures) from a suite's JSON report (the three report shapes used in this repo)."""
    j = json.loads(path.read_text(encoding="utf-8"))
    if "checks" in j and "summary" in j:  # NASA benchmark: PASS / FAIL / INFO / SKIP
        strict = [c for c in j["checks"] if c["status"] in ("PASS", "FAIL")]
        fails = [{"case": c["name"], "detail": str(c.get("detail") or c.get("value"))} for c in strict if c["status"] == "FAIL"]
        return len(strict) - len(fails), len(strict), fails
    rows = j.get("cases") or j.get("results") or j.get("checks") or []
    ok = lambda r: r.get("pass", r.get("ok", r.get("passed")))  # noqa: E731
    fails = [{"case": r.get("case") or r.get("test") or r.get("name"), "detail": r.get("detail", "")} for r in rows if not ok(r)]
    return len(rows) - len(fails), len(rows), fails


def _from_stdout(text: str) -> tuple[int, int, list[dict]]:
    passed = len(re.findall(r"^PASS ", text, re.M))
    fails = [{"case": m.strip(), "detail": ""} for m in re.findall(r"^FAIL (.*)$", text, re.M)]
    return passed, passed + len(fails), fails


def run(quick: bool = False) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "LUNAR_SKIP_BG_WARMUP": "1"}
    node = r"C:\Program Files\nodejs"
    if Path(node).exists():
        env["PATH"] = node + os.pathsep + env.get("PATH", "")
    results = []
    for name, script, report in SUITES:
        if quick and "benchmark" in script:
            continue
        t0 = time.perf_counter()
        p = subprocess.run([sys.executable, "-I", str(ROOT / script)], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        secs = time.perf_counter() - t0
        try:
            passed, total, fails = _from_report(OUT / report) if report else _from_stdout(p.stdout)
        except Exception as exc:  # the suite crashed before writing a report
            passed, total, fails = 0, 1, [{"case": "suite did not complete", "detail": f"{type(exc).__name__}: {exc}; {p.stderr[-300:]}"}]
        if p.returncode != 0 and not fails:  # non-zero exit without a recorded failure: report the crash
            fails = [{"case": "suite exited with an error", "detail": p.stderr[-300:] or p.stdout[-300:]}]
        results.append({"suite": name, "script": script, "passed": passed, "total": total, "ok": not fails, "seconds": round(secs, 1), "failures": fails})
    summary = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "ok": all(r["ok"] for r in results),
               "passed": sum(r["passed"] for r in results), "total": sum(r["total"] for r in results), "suites": results}
    (OUT / "test_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252: never crash on a symbol
        stream.reconfigure(errors="replace")
    s = run(quick="--quick" in sys.argv)
    print(f"\n{'Suite':36s} {'Passed':>8s} {'Time':>7s}  Status")
    print("-" * 64)
    for r in s["suites"]:
        print(f"{r['suite']:36s} {r['passed']:>4d}/{r['total']:<4d} {r['seconds']:>6.1f}s  {'OK' if r['ok'] else 'FAILED'}")
    print("-" * 64)
    print(f"{'TOTAL':36s} {s['passed']:>4d}/{s['total']:<4d}          {'ALL PASSED' if s['ok'] else 'FAILURES FOUND'}")
    for r in s["suites"]:
        for f in r["failures"]:
            print(f"  ✕ [{r['suite']}] {f['case']}: {str(f['detail'])[:160]}")
    print(f"\nSummary written to {OUT / 'test_summary.json'}")
    return 0 if s["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
