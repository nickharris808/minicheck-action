"""The install path the entrypoint actually takes, not the one its comment describes.

`entrypoint.sh` says the PyPI index is the fast path and that an explicit `minicheck-ref:` is what
diverts to git. That is only true if the *default* ref is empty. It was `"main"`, which is non-empty,
so `[[ -n "${MC_REF:-}" ]]` was true on every default run and the index branch was unreachable dead
code — the comment and the behaviour disagreed and nothing noticed.

These tests pin the contract in both directions, so the default can never silently defeat it again.
"""

from __future__ import annotations

import os
import re
import subprocess

import pytest
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ACTION_YML = os.path.join(ROOT, "action.yml")
ENTRYPOINT = os.path.join(ROOT, "entrypoint.sh")


def action() -> dict:
    with open(ACTION_YML) as fh:
        return yaml.safe_load(fh)


def test_the_default_ref_is_empty_so_the_index_branch_is_reachable():
    """A non-empty default makes `[[ -n "$MC_REF" ]]` always true and kills the PyPI path."""
    default = action()["inputs"]["minicheck-ref"]["default"]
    assert default == "", (
        f"minicheck-ref default is {default!r}; any non-empty default makes the guard in "
        "entrypoint.sh always true and the PyPI fast path unreachable"
    )


def test_the_entrypoint_still_has_an_index_branch_to_reach():
    """Guard against the fix being 'completed' by deleting the branch it was meant to enable."""
    src = open(ENTRYPOINT).read()
    assert re.search(r'pip install[^\n]*"minicheck>=', src), (
        "entrypoint.sh no longer attempts a PyPI install; the index fast path is gone"
    )
    assert "git+https://github.com/nickharris808/minicheck@${MC_REF:-main}" in src, (
        "the git fallback must survive and must still default to main when MC_REF is empty"
    )


@pytest.mark.parametrize(
    "mc_ref,expect_index_first",
    [("", True), ("main", False), ("v0.4.0", False), ("abc1234", False)],
)
def test_guard_semantics_match_the_documented_intent(mc_ref, expect_index_first):
    """Empty ref -> try the index first. Any explicit ref -> go straight to git."""
    script = f'MC_REF="{mc_ref}"\n' + 'if [[ -n "${MC_REF:-}" ]]; then echo git; else echo index; fi\n'
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == ("index" if expect_index_first else "git"), (
        f"MC_REF={mc_ref!r} took the {out!r} path"
    )


def test_an_empty_ref_still_resolves_to_main_in_the_git_fallback():
    """If PyPI is unreachable with an empty ref, the git form must not install from an empty ref."""
    out = subprocess.run(
        ["bash", "-c", 'MC_REF=""; echo "${MC_REF:-main}"'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == "main"
