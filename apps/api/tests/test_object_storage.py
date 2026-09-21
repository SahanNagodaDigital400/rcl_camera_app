"""`api.storage` — the seam, and the one rule it must never relax.

`OBJECT_STORAGE_ROOT` is **never defaulted**, for the reason `api.db` never
defaults `DATABASE_URL`: a service that guesses where to put files can write a
catalogue into whatever directory it happened to start in and report success —
and nobody finds out until the box is rebuilt.

Every other test in the suite runs with the variable set, so without this file
replacing the raise with `os.getcwd()` would leave the whole suite green. That
is the single change this file exists to fail on.

The rest of it is the driver's contract, asserted through
`create_object_store` rather than by constructing `FilesystemObjectStore`
directly: a test that built its own would pass on the day the factory started
handing out something else.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from api.storage import (
    OBJECT_STORAGE_ROOT,
    ObjectNotFound,
    ObjectStorageNotConfigured,
    create_object_store,
    get_object_store,
    valid_key,
)

KEY = "tiles/9c2f1e4a/2c9a0f13/view.jpg"


@pytest.mark.parametrize(
    ("label", "configured"),
    [("unset", None), ("empty", ""), ("whitespace only", "   \t\n ")],
)
def test_an_unconfigured_root_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, label: str, configured: str | None
) -> None:
    if configured is None:
        monkeypatch.delenv(OBJECT_STORAGE_ROOT, raising=False)
    else:
        monkeypatch.setenv(OBJECT_STORAGE_ROOT, configured)

    with pytest.raises(ObjectStorageNotConfigured) as refused:
        get_object_store()

    # The message has to name the variable: this failure reaches an operator
    # as a 500 on somebody's first catalogue write, and "not configured" with
    # no name is a half-hour of grep.
    assert OBJECT_STORAGE_ROOT in str(refused.value), label


def test_whitespace_around_a_real_root_is_ignored_rather_than_refused(
    tmp_path: Path,
) -> None:
    # A trailing newline is what a value read out of a file or a secret store
    # arrives with, and refusing it would be refusing a configured service.
    store = create_object_store(f"  {tmp_path}\n")
    store.put(KEY, b"bytes")

    assert (tmp_path / KEY).read_bytes() == b"bytes"


def test_a_written_object_reads_back_and_a_second_write_replaces_it(
    tmp_path: Path,
) -> None:
    store = create_object_store(str(tmp_path))

    store.put(KEY, b"first")
    assert store.get(KEY) == b"first"

    store.put(KEY, b"second")
    assert store.get(KEY) == b"second"


def test_reading_what_is_not_there_is_named_rather_than_an_ioerror(
    tmp_path: Path,
) -> None:
    # `api.catalogue` turns exactly this into the `404` for a row whose object
    # has vanished, so it has to be distinguishable from a disk failure.
    store = create_object_store(str(tmp_path))

    with pytest.raises(ObjectNotFound):
        store.get(KEY)


def test_deleting_what_is_not_there_succeeds(tmp_path: Path) -> None:
    # The cleanup path after a failed add deletes keys it may never have
    # written; a raise there would replace the failure the caller is being
    # told about.
    create_object_store(str(tmp_path)).delete(KEY)


def test_a_partial_write_is_never_visible_under_its_key(tmp_path: Path) -> None:
    # Written beside the target and renamed into place, so a crash mid-write
    # cannot leave a truncated derivative that a later read serves as a
    # corrupt image.
    store = create_object_store(str(tmp_path))
    store.put(KEY, b"x" * 4096)

    leftovers = [path.name for path in (tmp_path / KEY).parent.iterdir()]

    assert leftovers == ["view.jpg"]


def test_a_failed_write_leaves_the_old_bytes_and_no_litter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure half of the staged write — the half a successful `put` cannot show.

    Two things have to hold when the write raises. The key must still read the
    bytes that were there before, which is `os.replace` never having run; and
    the staging file must be gone, because its name begins with a dot and
    `valid_key` refuses it — so neither `delete` nor the add path's `_discard`
    could ever clear it, and only a human with a shell could.

    Without this, replacing the whole staged write with `path.write_bytes(data)`
    leaves every test in this file passing.
    """
    store = create_object_store(str(tmp_path))
    store.put(KEY, b"the bytes that were already there")

    def fail(*_: object, **__: object) -> int:
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "write_bytes", fail)

    with pytest.raises(OSError):
        store.put(KEY, b"x" * 4096)

    assert store.get(KEY) == b"the bytes that were already there"
    assert [path.name for path in (tmp_path / KEY).parent.iterdir()] == ["view.jpg"]


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/absolute/key",
        "../escape",
        "tiles/../../etc/passwd",
        "tiles/./view.jpg",
        "tiles//view.jpg",
        ".hidden",
    ],
)
def test_a_key_that_could_leave_the_root_is_refused(tmp_path: Path, key: str) -> None:
    # Keys are built from UUIDs and fixed words, so nothing a request can
    # influence reaches one — this is the belt to that braces, and it is what
    # lets the driver join a key onto a root without a traversal check
    # somebody has to remember at each call site.
    store = create_object_store(str(tmp_path))

    assert not valid_key(key)
    with pytest.raises(ValueError):
        store.put(key, b"bytes")


def test_the_protocol_offers_no_listing_and_no_signed_url() -> None:
    # AD-9: `apps/web` never receives a directly-usable storage reference. A
    # driver cannot grow one quietly while the protocol has no place for it,
    # and a listing has no caller and would be the first thing an
    # exfiltration path reached for.
    from api.storage import ObjectStore

    assert sorted(m for m in dir(ObjectStore) if not m.startswith("_")) == [
        "delete",
        "get",
        "put",
    ]
