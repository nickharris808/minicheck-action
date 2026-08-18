"""Aggregate per-spec results into one verdict, a SARIF file, and a job summary.

Split out of `entrypoint.sh` so it can be tested directly rather than only through a shell.

The aggregation rule is the same one the rest of the portfolio uses and the only one that is safe:
**ERROR > REFUTED > UNDETERMINED > PROVED**. A run is PROVED only when every spec was proved over a
complete search. Nothing is ever rounded up.
"""

from __future__ import annotations

import glob
import json
import os
import sys

SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
ICON = {"PROVED": "✅", "REFUTED": "❌", "UNDETERMINED": "❓", "ERROR": "⚠️"}


def load_index(results_dir: str) -> dict:
    """safe-name -> original spec path."""
    index = {}
    path = os.path.join(results_dir, "index.tsv")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if "\t" in line:
                key, value = line.rstrip("\n").split("\t", 1)
                index[key] = value
    return index


def collect(results_dir: str):
    index = load_index(results_dir)
    rows, merged = [], []
    counts = {"PROVED": 0, "REFUTED": 0, "UNDETERMINED": 0, "ERROR": 0}

    for path in sorted(glob.glob(os.path.join(results_dir, "spec*.json"))):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            # An unreadable result is an ERROR, never an absence. Skipping it here would let a
            # crashed check disappear from the report and the run come back green.
            data = {"ok": False, "verdict": "ERROR"}
        verdict = data.get("verdict", "ERROR")
        if verdict == "BAD_SPEC" or not data.get("ok", True):
            verdict = "ERROR"
        if verdict not in counts:
            verdict = "ERROR"
        counts[verdict] += 1

        key = os.path.basename(path)[: -len(".json")]
        rows.append({"spec": index.get(key, key), "verdict": verdict, "data": data, "key": key})

        sarif_path = os.path.join(results_dir, key + ".sarif")
        if os.path.exists(sarif_path):
            try:
                merged.extend(json.load(open(sarif_path, encoding="utf-8"))["runs"])
            except Exception:
                pass
    return rows, merged, counts


def aggregate(counts: dict) -> str:
    """ERROR > REFUTED > UNDETERMINED > PROVED. Never rounds up."""
    for verdict in ("ERROR", "REFUTED", "UNDETERMINED"):
        if counts.get(verdict):
            return verdict
    return "PROVED"


def write_summary(path: str, rows: list, counts: dict, agg: str, results_dir: str) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"### minicheck — {ICON.get(agg, '')} {agg}\n\n")
        fh.write("| spec | verdict | states | exhaustive |\n|---|---|---|---|\n")
        for row in rows:
            d = row["data"]
            fh.write(
                f"| `{row['spec']}` | {ICON.get(row['verdict'], '')} {row['verdict']} | "
                f"{d.get('reachable_states', '—')} | {'yes' if d.get('exhaustive') else 'NO'} |\n"
            )
        if counts["UNDETERMINED"]:
            fh.write(
                "\n> **UNDETERMINED is not a pass.** The search did not cover the whole state space "
                "for those specs, so nothing was established about them.\n"
            )
        for row in rows:
            if row["verdict"] != "REFUTED":
                continue
            mmd = os.path.join(results_dir, row["key"] + ".mmd")
            if not os.path.exists(mmd):
                continue
            body = open(mmd, encoding="utf-8").read().strip()
            if body.startswith("stateDiagram"):
                fh.write(f"\n<details><summary>Counterexample — <code>{row['spec']}</code></summary>\n\n")
                fh.write("```mermaid\n" + body + "\n```\n\n</details>\n")


def main() -> int:
    results_dir = os.environ["RESULTS_DIR"]
    fail_on = os.environ.get("MC_FAIL_ON", "undetermined").lower()
    sarif_out = os.environ.get("MC_SARIF", "").strip()
    want_summary = os.environ.get("MC_SUMMARY", "true").lower() == "true"

    rows, merged, counts = collect(results_dir)
    agg = aggregate(counts)

    if sarif_out and merged:
        with open(sarif_out, "w", encoding="utf-8") as fh:
            json.dump(
                {"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": merged},
                fh,
                indent=2,
            )
        print(f"wrote SARIF for {len(merged)} run(s) to {sarif_out}")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"verdict={agg}\n")
            fh.write(f"checked={len(rows)}\n")
            fh.write(f"refuted={counts['REFUTED']}\n")
            fh.write(f"undetermined={counts['UNDETERMINED']}\n")
            fh.write(f"sarif-file={sarif_out if sarif_out and merged else ''}\n")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if want_summary and summary:
        write_summary(summary, rows, counts, agg, results_dir)

    print(f"verdict: {agg}  (checked {len(rows)}: {counts})")

    failed = counts["REFUTED"] > 0 or counts["ERROR"] > 0
    if fail_on == "undetermined":
        failed = failed or counts["UNDETERMINED"] > 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
