"""Object storage — the seam, and the one driver that exists today.

**The provider is not pinned and this module does not guess one.**
`infra/README.md` lists "S3-compatible provider choice (AWS S3, Cloudflare R2,
self-hosted MinIO)" among the open infrastructure decisions and says to pin it
before infra work starts; it is not pinned. Adding an SDK against an unchosen
provider would be an untestable guess and an unflagged dependency, so what
ships is the protocol every caller codes against plus a filesystem driver
behind it. The S3 driver is one class and one `create_object_store` branch,
with no call site to change.

Nothing about that weakens the architecture's rules. AD-6 and AD-9 are about
who holds the credential and who the bytes travel through, not about which
vendor stores them: `apps/web` still receives no storage URL of any kind, every
byte in and out is proxied by an authenticated `apps/api` endpoint, and AD-7's
intake still runs before anything is written.

**`OBJECT_STORAGE_ROOT` is never defaulted**, for the reason `api.db` never
defaults `DATABASE_URL`: a service that guesses where to put files can write a
catalogue into a temporary directory and report success. A missing variable is
a named failure at the first write, not a surprise the week the disk is
cleared.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol, runtime_checkable

#: Where the filesystem driver writes. Required, never defaulted — see above.
OBJECT_STORAGE_ROOT = "OBJECT_STORAGE_ROOT"


class ObjectStorageNotConfigured(RuntimeError):
    """`OBJECT_STORAGE_ROOT` is missing. Named, so the fix is in the message."""


class ObjectNotFound(KeyError):
    """No object under that key. The catalogue read turns this into a `404`."""


#: What a key may contain. Keys are built by `api.catalogue` from UUIDs and
#: fixed words, so nothing a request can influence reaches one — this is the
#: belt to that braces, and the reason the filesystem driver can join a key
#: onto a root without a traversal check that has to be remembered. `..` cannot
#: match, because a path segment of two dots is not in the character class
#: followed by the separator rule below.
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


def valid_key(key: str) -> bool:
    """Whether `key` is a storage key this module will act on.

    A leading dot is refused on every segment, which is what rules out `..` and
    therefore every traversal: no segment can be `.` or `..`, no key can be
    absolute, and no key can be empty.
    """
    return bool(_KEY.match(key)) and ".." not in key.split("/")


@runtime_checkable
class ObjectStore(Protocol):
    """The three operations the catalogue needs, and deliberately no more.

    No listing, no signed URL, no copy. A listing has no caller and would be
    the first thing an exfiltration path reached for; a signed URL is exactly
    what AD-9 forbids, and leaving it out of the protocol means no driver can
    quietly grow one and no handler can quietly return one.
    """

    def put(self, key: str, data: bytes) -> None:
        """Write `data` at `key`, replacing whatever was there."""

    def get(self, key: str) -> bytes:
        """The bytes at `key`, or `ObjectNotFound`."""

    def delete(self, key: str) -> None:
        """Remove `key`. Idempotent: deleting what is not there is not an error."""


class FilesystemObjectStore:
    """An `ObjectStore` over a directory tree. The only driver today.

    Deliberately boring. Every property the catalogue depends on — a key maps
    to one object, a write replaces, a delete of nothing succeeds — is one an
    S3-compatible driver has too, so a test that passes against this one is a
    test about the catalogue rather than about the filesystem.

    Writes go to a temporary file in the same directory and are renamed into
    place, so a crash mid-write leaves no half-written derivative that a later
    read would serve as a corrupt image.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, key: str) -> Path:
        if not valid_key(key):
            raise ValueError(f"not a storage key: {key!r}")
        return self._root.joinpath(key)

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_name(f".{path.name}.partial")
        try:
            staging.write_bytes(data)
            os.replace(staging, path)
        except BaseException:
            # The staging name begins with a dot, which `valid_key` refuses, so
            # no caller — not `delete`, not the add path's compensating
            # `_discard` — can ever remove it afterwards. A full disk or an
            # interrupt would otherwise leave litter under the storage root
            # that only a human with a shell can clear.
            staging.unlink(missing_ok=True)
            raise

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except (FileNotFoundError, IsADirectoryError) as missing:
            raise ObjectNotFound(key) from missing

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def create_object_store(root: str | None = None) -> ObjectStore:
    """Build the configured store, or raise naming what is missing.

    The single construction point. When the provider is pinned, this grows one
    branch — on a scheme in the configured value, most likely — and every
    caller carries on calling `put`, `get` and `delete`.
    """
    configured = (os.environ.get(OBJECT_STORAGE_ROOT, "") if root is None else root).strip()
    if not configured:
        raise ObjectStorageNotConfigured(
            f"{OBJECT_STORAGE_ROOT} is not set. apps/api needs somewhere to keep reference "
            f"images, e.g. {OBJECT_STORAGE_ROOT}=/var/lib/rocell/objects — the S3-compatible "
            "provider is still an open infrastructure decision (infra/README.md), so the "
            "filesystem driver is what ships."
        )
    return FilesystemObjectStore(Path(configured))


def get_object_store() -> ObjectStore:
    """FastAPI dependency yielding the configured store.

    Constructed per request rather than held on `app.state`: building it is a
    `Path`, the configuration is read from the environment either way, and a
    store on application state would be one more thing a test has to arrange
    before it can point a request at a temporary directory.
    """
    return create_object_store()
