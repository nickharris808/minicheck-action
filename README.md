# minicheck-action

[![self-test](https://github.com/nickharris808/minicheck-action/actions/workflows/self-test.yml/badge.svg)](https://github.com/nickharris808/minicheck-action/actions/workflows/self-test.yml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Model-check your state machines in CI. Get the counterexample as a diagram, in the PR.**

Point it at your spec files. If an invariant breaks, the job fails and the summary shows the exact
interleaving that broke it — rendered, not as a table of numbers.

```yaml
- uses: nickharris808/minicheck-action@v1
  with:
    specs: "specs/**/*.spec.json"
```

## What you get

A job summary with a row per spec and a **Mermaid diagram of every counterexample**, which GitHub
draws inline:

> ### minicheck — ❌ REFUTED
>
> | spec | verdict | states | exhaustive |
> |---|---|---|---|
> | `specs/all_safe_here.spec.json` | ✅ PROVED | 2 | yes |
> | `specs/mutex.spec.json` | ❌ REFUTED | 4 | yes |

…plus a collapsible diagram under each refutation, and a SARIF file you can hand to
`github/codeql-action/upload-sarif` so the finding lands in the **Security** tab.

## The verdict is three-valued, and that changes the default

| Verdict | Meaning |
|---|---|
| `PROVED` | every reachable state was enumerated; the invariant held in all of them |
| `REFUTED` | a counterexample exists. It is shown, and it replays |
| `UNDETERMINED` | **the search did not finish, so nothing was established** |
| `ERROR` | a spec could not be checked at all |

**`UNDETERMINED` fails the job by default.** A gate that treats "I could not tell" as success is
worse than no gate, because it looks like evidence. Set `fail-on: refuted` if you consciously want
to accept unestablished specs — that choice is yours to make explicitly, not one made quietly for
you.

The run's verdict is the worst of its specs: **ERROR > REFUTED > UNDETERMINED > PROVED**. One
undetermined spec in a hundred proved ones makes the run undetermined.

**No spec matched the glob is `exit 3`, not success.** An action that examines nothing and reports
green is the same failure in a different costume.

## Inputs

| Input | Default | Description |
|---|---|---|
| `specs` | `**/*.spec.json` | glob for spec files |
| `fail-on` | `undetermined` | `undetermined` (strict) or `refuted` (accept unestablished specs) |
| `sarif-file` | `minicheck.sarif` | where to write SARIF; empty disables it |
| `int-bound` | `64` | largest magnitude an integer field may take |
| `max-states` | `200000` | stop after this many reachable states |
| `summary` | `true` | write the job summary with diagrams |
| `minicheck-ref` | `main` | git ref of `minicheck` to install |

## Outputs

| Output | Description |
|---|---|
| `verdict` | `PROVED`, `REFUTED`, `UNDETERMINED` or `ERROR` |
| `checked` | how many spec files were checked |
| `refuted` | how many had a counterexample |
| `undetermined` | how many could not be settled |
| `sarif-file` | path to the SARIF file, if one was written |

## Full example, with code scanning

```yaml
name: verify
on: [push, pull_request]
permissions:
  contents: read
  security-events: write        # required to upload SARIF

jobs:
  minicheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: check
        uses: nickharris808/minicheck-action@v1
        continue-on-error: true
        with:
          specs: "specs/**/*.spec.json"
          fail-on: undetermined
      - uses: github/codeql-action/upload-sarif@v3
        if: steps.check.outputs.sarif-file != ''
        with:
          sarif_file: ${{ steps.check.outputs.sarif-file }}
      - name: Enforce the verdict
        run: test "${{ steps.check.outputs.verdict }}" = "PROVED"
```

`continue-on-error` lets the SARIF upload run even on a failure — which is exactly when you want it.
The final step re-imposes the gate, so the job still fails.

## A spec looks like this

```json
{
  "name": "mutex",
  "fields": ["a", "b", "lock"],
  "initial": {"a": 0, "b": 0, "lock": 0},
  "transitions": [
    {"label": "a_enter", "when": {"a": 0, "lock": 0}, "set": {"a": 1, "lock": 1}},
    {"label": "b_enter", "when": {"b": 0, "lock": 0}, "set": {"b": 1, "lock": 1}}
  ],
  "invariants": {"not_both": {"forbid": {"a": 1, "b": 1}}}
}
```

`minicheck example > my.spec.json` gives you a starting point. Full format documentation is in
[`minicheck`](https://github.com/nickharris808/minicheck).

## Honest scope

**What a `PROVED` run establishes.** That every reachable state of the *models you wrote* satisfies
the invariants you declared. A model abstracts; an abstraction can hide a real defect. This checks
your spec, not your implementation.

**What it does not do.** It does not extract specs from your code, it does not check liveness unless
the spec declares a `goal`, and it cannot verify anything outside `int-bound` or `max-states` —
exceeding either yields `UNDETERMINED`, never a quiet pass.

## The portfolio

| | |
|---|---|
| [`minicheck`](https://github.com/nickharris808/minicheck) | the checker this action runs |
| [`protocol-bench`](https://github.com/nickharris808/protocol-bench) | 15 published IEEE 802.11 / 3GPP procedures with ground truth |
| [`minicheck-mcp`](https://github.com/nickharris808/minicheck-mcp) | the checker as an MCP server, for agents |
| [`failclosed`](https://github.com/nickharris808/failclosed) | default-deny ASGI middleware for verification-gated endpoints |
| [`polyfrac`](https://github.com/nickharris808/polyfrac) | exact rational arithmetic with Sturm root counting |

## Tests

```
python -m pytest tests/
```

20 tests over the aggregation rule and the exit contract — the two things that decide what your CI
gate is told.

## Licence

MIT.
