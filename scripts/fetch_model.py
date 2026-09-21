"""Download the ONNX backbone `shared/vision` embeds with. `make model` runs this.

346 MB of weights never enter git (`.gitignore`), so every machine fetches them
once. Three properties this script has and a `curl` in the Makefile would not:

* **The revision is pinned.** `Xenova/dinov2-base`'s `main` branch is somebody
  else's mutable pointer. AD-1 makes the model part of the pixel path and AD-14
  stamps a generation with the pipeline that built it, so a silently different
  set of weights is a silently invalidated index — the exact failure mode that
  raises no error. The commit below is the one the POC measured against.

* **The digest is checked.** A truncated download is the likelier failure by a
  wide margin at this size, and a half-written `model.onnx` fails later, inside
  ONNX Runtime, with a message about a protobuf rather than about a download.
  Written to a temporary file beside the target and renamed only once the hash
  matches, so an interrupted run never leaves a plausible-looking artifact.

* **It adds no dependency.** `urllib` is in the standard library. A
  once-per-machine fetch does not justify putting `huggingface_hub` (and its
  own dependency tree) into the workspace every developer installs — AGENTS.md
  asks for a new dependency to be flagged, and this is one worth not having.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

#: The Hugging Face repository the architecture spine's Stack table names, and
#: the exact commit the POC's numbers were measured on. Not `main`: see above.
REPO = "Xenova/dinov2-base"
REVISION = "d623d125a29e343851bcedff293fdc8b6bda292b"
REMOTE_PATH = "onnx/model.onnx"

URL = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{REMOTE_PATH}"

#: The file's LFS oid at that revision, which is its sha256.
EXPECTED_SHA256 = "de9c675d214f0171285f90f1d1d7716bce1c5e280e93826d071d57f7b9314d98"
EXPECTED_BYTES = 346_555_570

#: Where `shared_vision.pipeline` looks by default. Resolved from this file so
#: `make model` works from any working directory, and spelled out here rather
#: than imported so the fetch does not need the package (and its three
#: dependencies) to be installed first.
REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "shared" / "vision" / "shared_vision" / "models" / "model.onnx"

CHUNK = 1 << 20

#: How long to wait for the server between reads. Without it a connection that
#: opens and then stalls leaves `make model` hanging with no output and no
#: error — indistinguishable, to the developer watching it, from a slow
#: 346 MB download. Applied per socket operation, not to the transfer as a
#: whole, so a genuinely slow link still finishes.
TIMEOUT_SECONDS = 60


def digest(path: Path) -> str:
    """The sha256 of `path`, read a megabyte at a time rather than all at once."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            sha.update(block)
    return sha.hexdigest()


def download(url: str, destination: Path) -> None:
    """Stream `url` to `destination`, reporting progress on a terminal."""
    with urllib.request.urlopen(  # noqa: S310 - constant https URL
        url, timeout=TIMEOUT_SECONDS
    ) as response:
        total = int(response.headers.get("content-length") or EXPECTED_BYTES)
        done = 0
        with destination.open("wb") as handle:
            while block := response.read(CHUNK):
                handle.write(block)
                done += len(block)
                print(f"\r  {done / 1e6:6.0f} / {total / 1e6:.0f} MB", end="", flush=True)
    print()


def main() -> int:
    if TARGET.exists():
        if digest(TARGET) == EXPECTED_SHA256:
            print(f"model already present at {TARGET.relative_to(REPO_ROOT)}")
            return 0
        # Present and wrong is worse than absent: it is the state in which
        # every embedding is quietly produced by weights nobody chose.
        print(f"{TARGET} does not match the pinned digest; re-downloading", file=sys.stderr)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # Beside the target, so the rename below is atomic on the same filesystem.
    staging = TARGET.with_suffix(".onnx.partial")

    print(f"fetching {REPO}@{REVISION[:8]} {REMOTE_PATH} (~{EXPECTED_BYTES / 1e6:.0f} MB)")
    try:
        download(URL, staging)
    except (urllib.error.URLError, OSError) as failure:
        staging.unlink(missing_ok=True)
        print(f"download failed: {failure}", file=sys.stderr)
        return 1

    actual = digest(staging)
    if actual != EXPECTED_SHA256:
        staging.unlink(missing_ok=True)
        print(
            "digest mismatch — the download is truncated or the pinned revision moved.\n"
            f"  expected {EXPECTED_SHA256}\n  got      {actual}",
            file=sys.stderr,
        )
        return 1

    os.replace(staging, TARGET)
    print(f"model ready at {TARGET.relative_to(REPO_ROOT)}")
    return 0


def link_from(source: Path) -> int:
    """Adopt an existing copy instead of downloading 346 MB a second time.

    `poc/models/model.onnx` is the same artifact at the same revision on a
    machine that has already run the POC. Hard-linked rather than copied, and
    verified against the same digest as a download.
    """
    # Checked before the digest, or `make model FROM=/wrong/path` answers with
    # a `FileNotFoundError` traceback instead of the sentence written for it.
    if not source.is_file():
        print(f"{source} does not exist", file=sys.stderr)
        return 1
    # Adopting the target from itself would unlink the only copy below and then
    # fail on both the link and the copy — 346 MB destroyed by a command whose
    # whole purpose is to avoid re-downloading it.
    if source.resolve() == TARGET.resolve():
        print(f"model already installed at {TARGET.relative_to(REPO_ROOT)}")
        return 0
    if digest(source) != EXPECTED_SHA256:
        print(f"{source} is not the pinned model", file=sys.stderr)
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # Staged and renamed into place, exactly as `main` does, rather than
    # unlinking the target first: an interrupted `copyfile` would otherwise
    # leave an unverified 346 MB file under the name every embedding is
    # produced from, and nothing downstream looks at it again.
    staging = TARGET.with_suffix(".onnx.partial")
    staging.unlink(missing_ok=True)
    try:
        os.link(source, staging)
    except OSError:
        shutil.copyfile(source, staging)
        # Only the copy needs re-checking. A hard link is the same inode as the
        # file whose digest was just verified; a copy is new bytes that can be
        # truncated by a full disk halfway through.
        if digest(staging) != EXPECTED_SHA256:
            staging.unlink(missing_ok=True)
            print(f"the copy of {source} did not survive intact", file=sys.stderr)
            return 1
    os.replace(staging, TARGET)
    print(f"model ready at {TARGET.relative_to(REPO_ROOT)} (from {source})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(link_from(Path(sys.argv[1])))
    raise SystemExit(main())
