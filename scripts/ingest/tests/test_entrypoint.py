"""The stub must fail honestly rather than report success."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from ingest.__main__ import main

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_main_returns_a_failure_exit_code() -> None:
    assert main() == 1


def test_main_says_what_is_missing(capsys: pytest.CaptureFixture[str]) -> None:
    main()

    stderr = capsys.readouterr().err
    assert "not implemented yet" in stderr
    assert "Epic 2" in stderr


def test_module_execution_exits_one() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ingest"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    # Specifically 1, not merely non-zero: a ModuleNotFoundError also exits
    # non-zero, and would let this test pass for entirely the wrong reason.
    assert result.returncode == 1, result.stderr
    assert "not implemented yet" in result.stderr
    assert "Epic 2" in result.stderr
