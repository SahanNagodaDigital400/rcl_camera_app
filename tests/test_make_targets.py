"""The root Makefile's targets must be honest about what they do.

A target that printed nothing and exited 0 would let a later story mistake
"did nothing" for "already done", so each unimplemented one names the story or
epic that delivers it and exits non-zero.

`migrate` is implemented as of Story 1.2, so the property guarded here inverts:
it must no longer claim to be unimplemented, and it must refuse to run without
a `DATABASE_URL` rather than guessing one.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# target -> the phrase naming what delivers it
UNIMPLEMENTED = {
    "ingest": "Epic 2",
    "eval": "Epic 2",
}


MAKE = shutil.which("make")

pytestmark = pytest.mark.skipif(MAKE is None, reason="make is not on PATH")


def run_target(
    target: str,
    *,
    unset: tuple[str, ...] = (),
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run one Makefile target in a subprocess that is not part of this build.

    `make test` may itself be the caller, and MAKEFLAGS carries the parent's
    jobserver file descriptors. Inheriting them makes a nested make either warn
    about a disabled jobserver or block on descriptors this process does not
    hold, so both variables are dropped.
    """
    dropped = {"MAKEFLAGS", "MAKELEVEL", *unset}
    env = {k: v for k, v in os.environ.items() if k not in dropped}
    assert MAKE is not None

    try:
        return subprocess.run(
            [MAKE, target],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
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


def test_migrate_no_longer_claims_to_be_unimplemented() -> None:
    # Story 1.2 delivered it. If this target still advertised itself as
    # unimplemented, `make migrate` would read as a no-op to the next reader.
    result = run_target("migrate", unset=("DATABASE_URL",), timeout=300)
    output = result.stdout + result.stderr

    assert "not implemented yet" not in output
    assert "Story 1.2" not in output


def test_migrate_without_a_database_url_exits_non_zero_naming_it() -> None:
    # A migration runner that defaulted its connection string could migrate the
    # wrong database. It refuses, and says which variable is missing.
    result = run_target("migrate", unset=("DATABASE_URL",), timeout=300)

    assert result.returncode != 0, "make migrate ran without a DATABASE_URL"
    assert "DATABASE_URL" in result.stdout + result.stderr
