"""The root Makefile's not-yet-implemented targets must fail loudly.

A target that printed nothing and exited 0 would let a later story mistake
"did nothing" for "already done", so each one names the story or epic that
delivers it and exits non-zero.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# target -> the phrase naming what delivers it
UNIMPLEMENTED = {
    "migrate": "Story 1.2",
    "ingest": "Epic 2",
    "eval": "Epic 2",
}


MAKE = shutil.which("make")

pytestmark = pytest.mark.skipif(MAKE is None, reason="make is not on PATH")


def run_target(target: str) -> subprocess.CompletedProcess[str]:
    """Run one Makefile target in a subprocess that is not part of this build.

    `make test` may itself be the caller, and MAKEFLAGS carries the parent's
    jobserver file descriptors. Inheriting them makes a nested make either warn
    about a disabled jobserver or block on descriptors this process does not
    hold, so both variables are dropped.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MAKELEVEL"}}
    assert MAKE is not None

    try:
        return subprocess.run(
            [MAKE, target],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:  # pragma: no cover - a hung target
        pytest.fail(f"make {target} did not finish within {expired.timeout}s")


@pytest.mark.parametrize("target", sorted(UNIMPLEMENTED))
def test_unimplemented_target_exits_non_zero(target: str) -> None:
    result = run_target(target)
    assert result.returncode != 0, f"make {target} reported success while unimplemented"


@pytest.mark.parametrize(("target", "delivered_by"), sorted(UNIMPLEMENTED.items()))
def test_unimplemented_target_names_what_delivers_it(target: str, delivered_by: str) -> None:
    result = run_target(target)
    output = result.stdout + result.stderr
    assert "not implemented yet" in output, f"make {target} did not say it is unimplemented"
    assert delivered_by in output, (
        f"make {target} did not name {delivered_by} as its delivery point"
    )
