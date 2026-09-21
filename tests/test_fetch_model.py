"""`scripts/fetch_model.py` — the supply-chain gate on the weights, exercised.

The script is the only thing standing between `shared_vision.pipeline` and an
arbitrary 346 MB file: `config_hash()` stamps the preprocessing constants, not
the identity of the artifact, so two builds running different weights produce
an identical AD-14 stamp and compare vectors that were never comparable. The
digest check is what makes that impossible, and until this module existed it
was a branch nothing ran.

Nothing here downloads anything. `EXPECTED_SHA256` is monkeypatched to the hash
of a few bytes written in a temporary directory, which exercises the same
comparison the real 346 MB takes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "fetch_model.py"


def load_script() -> ModuleType:
    """Import the script by path — `scripts/` is not a package on `sys.path`."""
    spec = importlib.util.spec_from_file_location("fetch_model_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fetch_model() -> ModuleType:
    return load_script()


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_the_digest_helper_hashes_the_file_it_is_given(
    fetch_model: ModuleType, tmp_path: Path
) -> None:
    source = write(tmp_path / "weights.onnx", b"the pinned bytes")

    assert fetch_model.digest(source) == hashlib.sha256(b"the pinned bytes").hexdigest()


def test_an_adopted_copy_whose_digest_does_not_match_is_refused(
    fetch_model: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `make model FROM=<some other onnx>` is the plausible mistake: another
    # DINOv2 export, or the same repository's `main` a month later. The whole
    # point of the pin is that this is refused rather than adopted.
    target = tmp_path / "models" / "model.onnx"
    monkeypatch.setattr(fetch_model, "TARGET", target)
    monkeypatch.setattr(fetch_model, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(fetch_model, "EXPECTED_SHA256", hashlib.sha256(b"pinned").hexdigest())

    source = write(tmp_path / "elsewhere" / "model.onnx", b"not the pinned bytes")

    assert fetch_model.link_from(source) == 1
    assert not target.exists()


def test_an_adopted_copy_that_matches_the_pin_is_installed(
    fetch_model: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "models" / "model.onnx"
    monkeypatch.setattr(fetch_model, "TARGET", target)
    monkeypatch.setattr(fetch_model, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(fetch_model, "EXPECTED_SHA256", hashlib.sha256(b"pinned").hexdigest())

    source = write(tmp_path / "elsewhere" / "model.onnx", b"pinned")

    assert fetch_model.link_from(source) == 0
    assert target.read_bytes() == b"pinned"


def test_a_missing_source_is_named_rather_than_traced(
    fetch_model: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "models" / "model.onnx"
    monkeypatch.setattr(fetch_model, "TARGET", target)
    monkeypatch.setattr(fetch_model, "REPO_ROOT", tmp_path)

    assert fetch_model.link_from(tmp_path / "nowhere" / "model.onnx") == 1
    assert not target.exists()


def test_adopting_the_target_from_itself_leaves_the_model_in_place(
    fetch_model: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`make model FROM=shared/vision/shared_vision/models/model.onnx`.

    The installed path is the obvious thing to type, and without the identity
    guard the adoption path would link a file onto itself — 346 MB at risk from
    a command whose whole purpose is not to download it twice.
    """
    target = tmp_path / "models" / "model.onnx"
    write(target, b"pinned")
    monkeypatch.setattr(fetch_model, "TARGET", target)
    monkeypatch.setattr(fetch_model, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(fetch_model, "EXPECTED_SHA256", hashlib.sha256(b"pinned").hexdigest())

    assert fetch_model.link_from(target) == 0
    assert target.read_bytes() == b"pinned"


def test_an_interrupted_copy_never_lands_under_the_model_name(
    fetch_model: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The digest is checked on the source; the copy is what can go wrong after it.

    `os.link` fails across filesystems — adopting from an external disk is
    exactly when `FROM=` is worth typing — and the `copyfile` fallback can be
    truncated by a full disk. The source's digest says nothing about the bytes
    that actually landed, and nothing downstream ever looks at them again:
    `pipeline` loads whatever is at that path and stamps it with a hash that
    does not cover the artifact.
    """
    target = tmp_path / "models" / "model.onnx"
    write(target, b"the model that was already installed")
    monkeypatch.setattr(fetch_model, "TARGET", target)
    monkeypatch.setattr(fetch_model, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(fetch_model, "EXPECTED_SHA256", hashlib.sha256(b"pinned").hexdigest())

    def across_filesystems(*_: object, **__: object) -> None:
        raise OSError("Invalid cross-device link")

    def truncated(_: object, destination: str) -> None:
        Path(destination).write_bytes(b"pin")

    monkeypatch.setattr(fetch_model.os, "link", across_filesystems)
    monkeypatch.setattr(fetch_model.shutil, "copyfile", truncated)

    source = write(tmp_path / "elsewhere" / "model.onnx", b"pinned")

    assert fetch_model.link_from(source) == 1
    # The installed model is untouched, and no staging file is left behind for
    # a later run to trip over.
    assert target.read_bytes() == b"the model that was already installed"
    assert sorted(path.name for path in target.parent.iterdir()) == ["model.onnx"]


def test_the_pin_is_a_commit_and_not_a_branch(fetch_model: ModuleType) -> None:
    # `main` is somebody else's mutable pointer, and a silently different set
    # of weights is a silently invalidated index that raises no error.
    assert fetch_model.REVISION != "main"
    assert len(fetch_model.REVISION) == 40
    assert fetch_model.REVISION in fetch_model.URL
    assert len(fetch_model.EXPECTED_SHA256) == 64
