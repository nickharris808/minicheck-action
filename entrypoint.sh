#!/usr/bin/env bash
# Check every matching spec, aggregate the verdicts, and report where people look.
#
#   exit 0  every spec met the configured threshold
#   exit 1  at least one spec did not
#   exit 3  misconfigured — no spec matched the glob. Never a silent pass on nothing.
#
# That last one matters more than it looks: an action that finds no files and exits 0 is reporting
# "everything is fine" about a repository it never examined.
set -euo pipefail

# `minicheck` is on PyPI, so the index is the fast path and needs no `git` on the runner.
# An explicit `minicheck-ref:` means the caller wants a specific commit, which only the git form
# can give them — so that input takes priority over the index.
if ! python -c "import minicheck" 2>/dev/null; then
  if [[ -n "${MC_REF:-}" ]] || ! python -m pip install --quiet --disable-pip-version-check "minicheck>=0.4"; then
    python -m pip install --quiet --disable-pip-version-check \
      "minicheck @ git+https://github.com/nickharris808/minicheck@${MC_REF:-main}"
  fi
fi

SPECS_GLOB="${MC_SPECS:-**/*.spec.json}"

# `while read` rather than `mapfile`: mapfile is a bash 4+ builtin and this should run anywhere.
FILES=()
while IFS= read -r line; do
  [[ -n "$line" ]] && FILES+=("$line")
done < <(python -c '
import glob, os
pattern = os.environ.get("MC_SPECS", "**/*.spec.json")
for p in sorted(glob.glob(pattern, recursive=True)):
    if os.path.isfile(p):
        print(p)
')

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "::error::no spec files matched ${SPECS_GLOB}. Refusing to report success for a repository that was never checked."
  {
    echo "verdict=ERROR"
    echo "checked=0"
    echo "refuted=0"
    echo "undetermined=0"
    echo "sarif-file="
  } >> "$GITHUB_OUTPUT"
  exit 3
fi

echo "checking ${#FILES[@]} spec file(s)"
RESULTS_DIR="$(mktemp -d)"
export RESULTS_DIR
: > "${RESULTS_DIR}/index.tsv"

i=0
for f in "${FILES[@]}"; do
  # An index file, not a reversible name encoding. A spec path may legitimately contain "_", and
  # deriving the original back from a mangled name silently renamed those files in the report.
  i=$((i + 1))
  safe="spec${i}"
  printf '%s\t%s\n' "$safe" "$f" >> "${RESULTS_DIR}/index.tsv"

  minicheck check "$f" --format json \
    --int-bound "${MC_INT_BOUND:-64}" --max-states "${MC_MAX_STATES:-200000}" \
    > "${RESULTS_DIR}/${safe}.json" 2>"${RESULTS_DIR}/${safe}.err" || true
  # Diagram and SARIF are best-effort per file: a spec too large to draw must not fail the job.
  minicheck check "$f" --format mermaid \
    --int-bound "${MC_INT_BOUND:-64}" --max-states "${MC_MAX_STATES:-200000}" \
    > "${RESULTS_DIR}/${safe}.mmd" 2>/dev/null || true
  minicheck check "$f" --format sarif \
    --int-bound "${MC_INT_BOUND:-64}" --max-states "${MC_MAX_STATES:-200000}" \
    > "${RESULTS_DIR}/${safe}.sarif" 2>/dev/null || true
done

python "${GITHUB_ACTION_PATH:-$(dirname "$0")}/aggregate.py"
