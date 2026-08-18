"""The aggregation rule is the whole action.

An action reports one number to a CI gate, so the only thing that really matters is that the number
is never better than the evidence. Every test here checks the same property from a different angle:
**nothing is ever rounded up.**
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aggregate import aggregate, collect, load_index, main  # noqa: E402


def make_results(tmp_path, specs):
    """specs: {name: verdict-or-dict}. Writes the per-spec JSON the entrypoint would have."""
    index = tmp_path / "index.tsv"
    lines = []
    for i, (name, value) in enumerate(specs.items(), start=1):
        key = f"spec{i}"
        lines.append(f"{key}\t{name}")
        payload = (
            value
            if isinstance(value, dict)
            else {
                "ok": True,
                "verdict": value,
                "reachable_states": 4,
                "exhaustive": value != "UNDETERMINED",
            }
        )
        (tmp_path / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(tmp_path)


# ------------------------------------------------------------------------- the aggregation rule
@pytest.mark.parametrize(
    "counts,expected",
    [
        ({"PROVED": 3, "REFUTED": 0, "UNDETERMINED": 0, "ERROR": 0}, "PROVED"),
        ({"PROVED": 2, "REFUTED": 0, "UNDETERMINED": 1, "ERROR": 0}, "UNDETERMINED"),
        ({"PROVED": 2, "REFUTED": 1, "UNDETERMINED": 0, "ERROR": 0}, "REFUTED"),
        ({"PROVED": 0, "REFUTED": 1, "UNDETERMINED": 1, "ERROR": 0}, "REFUTED"),
        ({"PROVED": 5, "REFUTED": 1, "UNDETERMINED": 1, "ERROR": 1}, "ERROR"),
        ({"PROVED": 0, "REFUTED": 0, "UNDETERMINED": 0, "ERROR": 0}, "PROVED"),
    ],
)
def test_aggregate_precedence(counts, expected):
    assert aggregate(counts) == expected


def test_one_undetermined_spec_sinks_an_otherwise_proved_run():
    """The case that would be tempting to round up, and must not be."""
    assert aggregate({"PROVED": 99, "REFUTED": 0, "UNDETERMINED": 1, "ERROR": 0}) == "UNDETERMINED"


# ------------------------------------------------------------------------------ result collection
def test_collect_reads_verdicts_and_resolves_names(tmp_path):
    d = make_results(tmp_path, {"a/mutex.spec.json": "REFUTED", "b/ok.spec.json": "PROVED"})
    rows, _merged, counts = collect(d)
    assert counts["REFUTED"] == 1 and counts["PROVED"] == 1
    assert {r["spec"] for r in rows} == {"a/mutex.spec.json", "b/ok.spec.json"}


def test_a_filename_containing_an_underscore_is_not_mangled(tmp_path):
    """An earlier version derived the path back from a mangled name and renamed these files."""
    d = make_results(tmp_path, {"deep/my_spec_name.spec.json": "PROVED"})
    rows, _m, _c = collect(d)
    assert rows[0]["spec"] == "deep/my_spec_name.spec.json"


def test_an_unreadable_result_becomes_an_error_not_an_absence(tmp_path):
    """A crashed check that vanishes from the report would let the run come back green."""
    (tmp_path / "index.tsv").write_text("spec1\tbroken.spec.json\n", encoding="utf-8")
    (tmp_path / "spec1.json").write_text("this is not json", encoding="utf-8")
    rows, _m, counts = collect(str(tmp_path))
    assert counts["ERROR"] == 1
    assert len(rows) == 1


def test_a_bad_spec_verdict_is_normalised_to_error(tmp_path):
    d = make_results(tmp_path, {"x.spec.json": {"ok": False, "verdict": "BAD_SPEC"}})
    _rows, _m, counts = collect(d)
    assert counts["ERROR"] == 1


def test_an_unknown_verdict_string_is_treated_as_an_error(tmp_path):
    """Anything the action does not understand must not be optimistically ignored."""
    d = make_results(tmp_path, {"x.spec.json": {"ok": True, "verdict": "SOMETHING_NEW"}})
    _rows, _m, counts = collect(d)
    assert counts["ERROR"] == 1


def test_load_index_tolerates_a_missing_file(tmp_path):
    assert load_index(str(tmp_path)) == {}


# ------------------------------------------------------------------------------ the exit contract
def run_main(results_dir, tmp_path, **env):
    out = tmp_path / "gh_out.txt"
    out.write_text("", encoding="utf-8")
    old = dict(os.environ)
    os.environ.update(
        {
            "RESULTS_DIR": results_dir,
            "GITHUB_OUTPUT": str(out),
            "MC_SUMMARY": "false",
            "MC_SARIF": "",
            **env,
        }
    )
    os.environ.pop("GITHUB_STEP_SUMMARY", None)
    try:
        code = main()
    finally:
        os.environ.clear()
        os.environ.update(old)
    return code, out.read_text(encoding="utf-8")


def test_a_refutation_fails_the_job(tmp_path):
    (tmp_path / "r").mkdir()
    d = make_results(tmp_path / "r", {"a.spec.json": "REFUTED"})
    code, out = run_main(d, tmp_path)
    assert code == 1
    assert "verdict=REFUTED" in out


def test_undetermined_fails_by_default(tmp_path):
    (tmp_path / "u").mkdir()
    d = make_results(tmp_path / "u", {"a.spec.json": "UNDETERMINED"})
    code, out = run_main(d, tmp_path, MC_FAIL_ON="undetermined")
    assert code == 1
    assert "verdict=UNDETERMINED" in out


def test_undetermined_can_be_accepted_deliberately(tmp_path):
    (tmp_path / "u2").mkdir()
    d = make_results(tmp_path / "u2", {"a.spec.json": "UNDETERMINED"})
    code, _ = run_main(d, tmp_path, MC_FAIL_ON="refuted")
    assert code == 0


def test_fail_on_refuted_still_fails_on_a_refutation(tmp_path):
    """Accepting "I could not tell" must not also accept "I found a bug"."""
    (tmp_path / "r2").mkdir()
    d = make_results(tmp_path / "r2", {"a.spec.json": "REFUTED"})
    code, _ = run_main(d, tmp_path, MC_FAIL_ON="refuted")
    assert code == 1


def test_fail_on_refuted_still_fails_on_an_error(tmp_path):
    (tmp_path / "e").mkdir()
    d = make_results(tmp_path / "e", {"a.spec.json": {"ok": False, "verdict": "BAD_SPEC"}})
    code, _ = run_main(d, tmp_path, MC_FAIL_ON="refuted")
    assert code == 1


def test_an_all_proved_run_passes(tmp_path):
    (tmp_path / "p").mkdir()
    d = make_results(tmp_path / "p", {"a.spec.json": "PROVED", "b.spec.json": "PROVED"})
    code, out = run_main(d, tmp_path)
    assert code == 0
    assert "verdict=PROVED" in out
    assert "checked=2" in out


# --------------------------------------------------------------------------------- job summary
def test_the_summary_flags_undetermined_as_not_a_pass(tmp_path):
    (tmp_path / "s").mkdir()
    d = make_results(tmp_path / "s", {"a.spec.json": "UNDETERMINED"})
    summary = tmp_path / "summary.md"
    out = tmp_path / "o.txt"
    out.write_text("", encoding="utf-8")
    old = dict(os.environ)
    os.environ.update(
        {
            "RESULTS_DIR": d,
            "GITHUB_OUTPUT": str(out),
            "GITHUB_STEP_SUMMARY": str(summary),
            "MC_SUMMARY": "true",
            "MC_SARIF": "",
            "MC_FAIL_ON": "undetermined",
        }
    )
    try:
        main()
    finally:
        os.environ.clear()
        os.environ.update(old)
    text = summary.read_text(encoding="utf-8")
    assert "UNDETERMINED is not a pass" in text
    assert "❓" in text
