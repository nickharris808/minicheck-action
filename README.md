# minicheck-action

[![self-test](https://github.com/nickharris808/minicheck-action/actions/workflows/self-test.yml/badge.svg)](https://github.com/nickharris808/minicheck-action/actions/workflows/self-test.yml)
[![tests](https://img.shields.io/badge/tests-20%20passing-brightgreen)](tests/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![marketplace](https://img.shields.io/badge/GitHub-Action-blue)
[![docs](https://img.shields.io/badge/docs-verification--docs-blue)](https://nickharris808.github.io/verification-docs/)

**Model-check your state machines in CI. Get the counterexample as a diagram, in the PR.**

Point it at your spec files. If an invariant breaks, the job fails and the summary shows the exact
interleaving that broke it — rendered, not as a table of numbers.

## Why this exists

Concurrency bugs are found in code review or not at all, because the alternative — adopting a model
checker — means adopting a toolchain: a separate language, a separate binary, a separate build step.
So the retry loop, the lock protocol and the session lifecycle get reasoned about in prose, and the
interleaving nobody imagined ships.

This makes the check a step in a workflow file. The model lives next to the code, it runs on every
push, and when it breaks the PR shows you *how* — with a picture rather than a paragraph.

## Install

There is nothing to `pip install`. Reference the Action from a workflow and it installs its own
dependency on first run:

```yaml
- uses: nickharris808/minicheck-action@v1
  with:
    specs: "specs/**/*.spec.json"
```

The Action is a **composite** action — it runs `bash` on the runner, so it needs `python` on `PATH`
(every `ubuntu-latest` image has it) and no container. It installs
[`minicheck`](https://pypi.org/project/minicheck/) from PyPI, falling back to a `git+` install if the
index is unreachable, and skips the install entirely when `minicheck` is already importable. Set
`minicheck-ref:` to force the `git+` path at a chosen ref.

## 30-second quickstart

Two specs, one that holds and one that does not. Everything below is the **real output** of the
Action's own `entrypoint.sh`, run locally with `GITHUB_OUTPUT` and `GITHUB_STEP_SUMMARY` pointed at
files.

```console
$ minicheck example > specs/mutex.spec.json
$ cat > specs/all_safe_here.spec.json <<'EOF'
{"name": "safe", "fields": ["n"], "initial": {"n": 0},
 "transitions": [{"label": "tick", "when": {"n": 0}, "set": {"n": 1}}],
 "invariants": {"n_small": {"forbid": {"n": 2}}}}
EOF
$ MC_SPECS='specs/**/*.spec.json' ./entrypoint.sh
checking 2 spec file(s)
wrote SARIF for 2 run(s) to minicheck.sarif
verdict: REFUTED  (checked 2: {'PROVED': 1, 'REFUTED': 1, 'UNDETERMINED': 0, 'ERROR': 0})
$ echo $?
1
$ cat "$GITHUB_OUTPUT"
verdict=REFUTED
checked=2
refuted=1
undetermined=0
sarif-file=minicheck.sarif
```

Point it at a glob that matches nothing and it refuses rather than reporting green:

```console
$ MC_SPECS='nope/**/*.spec.json' ./entrypoint.sh
::error::no spec files matched nope/**/*.spec.json. Refusing to report success for a repository that was never checked.
$ echo $?
3
```

## What you get

A job summary with a row per spec and a **Mermaid diagram of every counterexample**, which GitHub
draws inline. This is the real `GITHUB_STEP_SUMMARY` from the run above:

> ### minicheck — ❌ REFUTED
>
> | spec | verdict | states | exhaustive |
> |---|---|---|---|
> | `specs/all_safe_here.spec.json` | ✅ PROVED | 2 | yes |
> | `specs/mutex.spec.json` | ❌ REFUTED | 6 | yes |
>
> <details><summary>Counterexample — <code>specs/mutex.spec.json</code></summary>
>
> ```
> stateDiagram-v2
>     %% verdict: REFUTED
>     [*] --> S0
>     S0 : a=0, b=0, lock=0
>     S1 : a=1, b=0, lock=1
>     S3 : a=1, b=1, lock=1
>     S0 --> S1 : 1. a_enter
>     S1 --> S3 : 2. b_enter
>     class S0 cex
>     class S1 cex
>     class S3 cex
>     classDef cex fill:#fdd,stroke:#c00,stroke-width:2px
> ```
>
> </details>

(The diagram above is abridged — the real one also carries the non-counterexample states and edges,
so you can see the paths *not* taken. The numbered `1.`/`2.` edges and the `cex` classes are the
counterexample.)

…plus a SARIF file you can hand to `github/codeql-action/upload-sarif` so the finding lands in the
**Security** tab.

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

**It cannot audit the spec you wrote.** A spec whose invariant is trivially satisfied will show
`PROVED`, because it genuinely is — it just verifies nothing. `minicheck` emits a warning for that
case; read the log, not only the badge.

**Failing is best-effort in exactly two places, deliberately.** Rendering a diagram and writing SARIF
are per-file and non-fatal: a spec too large to draw must not turn a real verdict into a build error.
The verdict itself is never best-effort.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | every spec met the configured threshold |
| `1` | at least one did not |
| `3` | **misconfigured** — no spec matched the glob. A scan of nothing never reports success. |

## Troubleshooting

**The job fails with `exit 3` and `no spec files matched`.** The glob matched nothing. Globs are
expanded by the Action in Python with `recursive=True`, relative to the workspace root — so
`specs/**/*.spec.json` is right and `./specs/**.spec.json` is not. Run
`python -c "import glob; print(glob.glob('YOUR_GLOB', recursive=True))"` locally to check it.

**Everything is `UNDETERMINED` and I did not change the specs.** A field grows past `int-bound`
(default 64) or the space passed `max-states` (default 200000). The log names which, per spec. Raise
the bound or add a `when` guard that stops the growth. Do **not** reach for `fail-on: refuted` to
silence it — that accepts unestablished specs across the board, not just this one.

**The SARIF upload step is skipped.** `github/codeql-action/upload-sarif` only runs if the Action
step ran, and a failing step stops the job. Add `continue-on-error: true` to the check step and
re-impose the gate afterwards — the [full example](#full-example-with-code-scanning) does exactly
that.

**`Resource not accessible by integration` on the SARIF upload.** The workflow needs
`permissions: security-events: write`. It is not granted by default.

**A refuted spec produced no diagram.** Rendering is refused above `--max-nodes` (default 60) because
a hairball is not a diagram. The verdict, the state count and the SARIF entry are all still there.

**The verdict is worse than any single spec looks.** The run's verdict is the worst of its specs:
**ERROR > REFUTED > UNDETERMINED > PROVED**. One undetermined spec among a hundred proved ones makes
the run undetermined.

**It reinstalls `minicheck` on every run.** It does not — the entrypoint tries `import minicheck`
first and installs only if that fails. If you cache it or pre-install it in an earlier step, the
Action uses yours.

## FAQ

**"Why does `UNDETERMINED` fail my build? Nothing was found."**
Nothing was *looked at*, which is different. The search stopped before covering the space, so no
invariant was established. A gate that treats "I could not tell" as success is worse than no gate,
because it looks like evidence. `fail-on: refuted` is there if you want to accept that — the point is
that it becomes a line in your workflow file rather than a default someone chose for you.

**"Isn't `fail-on: refuted` an escape hatch that defeats the point?"**
It widens only the undetermined case. A counterexample still fails the build under either setting. A
flag meaning "I accept not knowing" must not also mean "I accept known-broken".

**"Why not just use SPIN or TLC in CI?"**
For a model that has outgrown this, do. `minicheck` exports to both — `--format promela` and
`--format tla` — precisely so that adopting this does not strand you. This Action exists for the
invariant you would otherwise not check at all, because setting up a real toolchain was more work
than the check was worth.

**"Can it check my code, or do I have to write a separate model?"**
You write the model. It does not extract specs from source, and that limitation is load-bearing
rather than a roadmap item: the abstraction is the part a human has to get right, and a tool that
guessed it would produce confident verdicts about the wrong system.

**"Why is a green run not proof that my system is correct?"**
Because it is proof about the *spec*. A model abstracts, and an abstraction can hide a real defect.
The useful reading of a green run is "the interleavings I described cannot reach the state I
forbade" — which is a real and checkable thing, and less than "my system is correct".

**"The `v1` tag — is it moving?"**
`v1` tracks the latest v1.x. Pin the full SHA if you need byte-stability, which is the normal advice
for any third-party Action.

## Tests

```
pip install "minicheck @ git+https://github.com/nickharris808/minicheck.git" pytest && pytest
```

20 tests over `aggregate.py` — verdict precedence, the summary renderer, SARIF shaping, and the
index-file mapping that stops a spec path containing `_` from being silently renamed in the report.

On top of those, the [self-test workflow](.github/workflows/self-test.yml) runs the **whole Action**
on every push in four jobs: the unit tests, a refuted spec that **must fail** the job, a proved spec
that **must pass**, and an undetermined spec that **must fail by default**. If the gate ever stops
gating, the build goes red.

## The portfolio

| | |
|---|---|
| [`minicheck`](https://github.com/nickharris808/minicheck) | The engine: an explicit-state model checker with a CLI. Shortest counterexamples, no required dependencies. |
| [`protocol-bench`](https://github.com/nickharris808/protocol-bench) | Published IEEE 802.11 / 3GPP procedures with ground-truth verdicts. A claimed detection must **replay**. |
| [`specforge`](https://github.com/nickharris808/specforge) | A benchmark that cannot be memorised — ground truth is *computed* by the checker, not written down. |
| [`minicheck-mcp`](https://github.com/nickharris808/minicheck-mcp) | The checker as an **MCP server**, so an agent can verify a state machine instead of guessing. |
| [`minicheck-action`](https://github.com/nickharris808/minicheck-action) ← *you are here* | Model-check every spec in a repo, in CI. Diagrams in the PR, SARIF in the Security tab. |
| [`protocol-bench-action`](https://github.com/nickharris808/protocol-bench-action) | Score a submission in CI and fail the build if a claimed detection cannot be proved by replay. |
| [`failclosed`](https://github.com/nickharris808/failclosed) | Default-deny ASGI middleware: a gated endpoint succeeds only on an affirmative verdict. |
| [`polyfrac`](https://github.com/nickharris808/polyfrac) | Exact polynomial and rational-function arithmetic over ℚ with Sturm real-root counting. Zero deps. |
| [**the docs site**](https://nickharris808.github.io/verification-docs/) | The front door: why a verdict you cannot check is not a verdict, and how these compose. |

One idea runs through all of them: **a verdict you cannot check is not a verdict** — and its
corollary, which governs every surface here: *undetermined is not a pass.*

**Try it in the browser** · [model-check a state machine](https://huggingface.co/spaces/nickh007/protocol-bench-demo) · [the specforge leaderboard](https://huggingface.co/spaces/nickh007/specforge-leaderboard)

**Ground-truth data** · [protocol-bench](https://huggingface.co/datasets/nickh007/protocol-bench) · [specforge](https://huggingface.co/datasets/nickh007/specforge)

## Documentation

Full documentation, including the concepts guide and an honest comparison against TLA+, SPIN, Alloy
and CBMC, is at **[https://nickharris808.github.io/verification-docs/](https://nickharris808.github.io/verification-docs/)**.

## Contributing

Bug reports and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). A counterexample
that this tool gets wrong is the single most useful thing you can send.

## Citing

Citation metadata is in [CITATION.cff](CITATION.cff); GitHub renders a *Cite this repository* button
from it.

## Licence

MIT. See [LICENSE](LICENSE).
