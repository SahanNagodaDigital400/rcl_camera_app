"""`POST /scans` — the match floor, and the env var that moves it.

Two levels, for the reason `test_anomaly_flagging.py` splits the same way: the
parsing of `TILEMATCH_SCAN_MATCH_FLOOR` is a pure function of the environment
and is tested by reloading the module, while what the bar *does* to a response
is only honest through the real route.

**None of this needs an ONNX model.** The cases below that need scored
Candidates stub `api.scan.find_candidates` — the bar is applied in `submit_scan`
after the search returns, precisely because it is a display decision and not a
pipeline one, so the seam is exactly where the test needs it. That also keeps
these tests about the filter rather than about retrieval, which
`test_scan_submission.py` already covers against a real index.

**The bar is not a confidence signal** (AD-20), and nothing here should ever be
read as asserting that it is. The POC measured correct and wrong top-1 scores
as almost indistinguishable (median 0.918 against 0.907); these tests pin that
the floor trims a tail deterministically, not that what survives it is right.
"""

from __future__ import annotations

import importlib
import io
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
from api import scan
from api.catalogue import Candidate
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.user import Role

MakeUser = Callable[..., Any]

SCANS = "/scans"
LOGIN = "/auth/login"


def jpeg_bytes() -> bytes:
    """A textured patch as JPEG — `test_scan_submission.jpeg_bytes`, restated.

    Copied rather than imported: pytest runs this suite under
    `--import-mode=importlib` over directories with no `__init__.py`, so one
    test module is not importable from another. The bytes only have to survive
    intake and the crop — the search that would consume them is stubbed out
    below — so this is the whole of what that helper does that matters here.
    """
    rng = np.random.default_rng(5)
    image = Image.fromarray(rng.integers(0, 255, (320, 320, 3), dtype=np.uint8), "RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


def submit_scan(client: TestClient) -> Any:
    """`POST /scans` as multipart, declaring no Size — the "All sizes" default."""
    return client.post(
        SCANS,
        data={"crop_x": 0.1, "crop_y": 0.1, "crop_width": 0.8, "crop_height": 0.8},
        files=[("image", ("scan.jpg", jpeg_bytes(), "image/jpeg"))],
    )


def _candidate(score: float, code: str) -> Candidate:
    """One scored Candidate, shaped as `find_candidates` returns it.

    `rank` is passed but never read by the filter under test — order in the
    list is the rank (`ScanCandidate`'s own contract), and the assertions below
    check the surviving *order*, never this field.
    """
    return Candidate(
        rank=1,
        tile_id=uuid4(),
        code=code,
        size="45X90",
        category="POLISH",
        face_number=None,
        score=score,
    )


def _stub_search(
    monkeypatch: pytest.MonkeyPatch, candidates: list[Candidate], floor: float
) -> None:
    """Make the route see exactly `candidates`, at exactly `floor`.

    `find_candidates` and `primary_reference_image_ids` are patched on
    `api.scan`, not on `api.catalogue`: the handler imported both names into
    its own namespace, so that is where the lookup actually happens.

    `MATCH_FLOOR` is set with `setattr` rather than by reloading the module
    with the env var set — reloading `api.scan` would rebind its `APIRouter`
    and detach every route from the already-built app this test's client
    drives. The env var's own parsing is tested separately below.
    """
    monkeypatch.setattr(scan, "MATCH_FLOOR", floor)
    monkeypatch.setattr(scan, "find_candidates", lambda conn, image, size=None: list(candidates))
    monkeypatch.setattr(
        scan,
        "primary_reference_image_ids",
        lambda conn, tile_ids: {tile_id: uuid4() for tile_id in tile_ids},
    )


# --- What the bar does to a response ---------------------------------------------


def test_candidates_below_the_floor_are_not_returned(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kept set is exactly those at or above the bar, in the search's order."""
    account = make_user(role=Role.STAFF)
    sign_in(client, account)

    _stub_search(
        monkeypatch,
        [_candidate(0.95, "KEPT-A"), _candidate(0.60, "KEPT-B"), _candidate(0.20, "DROPPED")],
        floor=0.50,
    )

    response = submit_scan(client)

    assert response.status_code == 200
    assert [candidate["code"] for candidate in response.json()] == ["KEPT-A", "KEPT-B"]


def test_a_candidate_exactly_on_the_floor_is_kept(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bar is `>=`, not `>`.

    The boundary is worth pinning rather than assuming: a Candidate scoring
    precisely the configured value is at the bar, not below it, and an
    operator who sets the floor to a score they have observed expects that
    score to survive it.
    """
    account = make_user(role=Role.STAFF)
    sign_in(client, account)

    _stub_search(monkeypatch, [_candidate(0.50, "ON-THE-BAR")], floor=0.50)

    response = submit_scan(client)

    assert response.status_code == 200
    assert [candidate["code"] for candidate in response.json()] == ["ON-THE-BAR"]


def test_nothing_clearing_the_floor_is_an_empty_200_not_an_error(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "No confident match" is an answer, not a failure.

    The same empty array an empty catalogue produces, which `ResultsScreen`
    already renders as `NO_MATCH` — so a scan trimmed to nothing needs no new
    status, no error envelope and no client change.
    """
    account = make_user(role=Role.STAFF)
    sign_in(client, account)

    _stub_search(monkeypatch, [_candidate(0.30, "TOO-LOW")], floor=0.50)

    response = submit_scan(client)

    assert response.status_code == 200
    assert response.json() == []


def test_the_persisted_snapshot_matches_the_trimmed_answer(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """History records what the staff member was shown, never the pre-trim list.

    AD-10's snapshot is of the answer, so a Candidate the bar hid must not
    reappear when the same scan is read back from `GET /scans`.
    """
    account = make_user(role=Role.STAFF)
    sign_in(client, account)

    _stub_search(monkeypatch, [_candidate(0.95, "KEPT"), _candidate(0.10, "DROPPED")], floor=0.50)

    assert submit_scan(client).status_code == 200

    history = client.get("/scans")
    assert history.status_code == 200
    entries = history.json()
    assert len(entries) == 1
    assert [candidate["code"] for candidate in entries[0]["candidates"]] == ["KEPT"]


def test_no_similarity_value_survives_the_filter_into_the_body(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AD-20 — the floor reads the score; the response still never carries it.

    The one regression this whole feature could plausibly introduce: a bar
    makes the score feel like something the client should see. It is not, and
    `ScanCandidate`'s closed shape is what stops it, so this asserts the keys
    rather than merely the absence of one spelling.
    """
    account = make_user(role=Role.STAFF)
    sign_in(client, account)

    _stub_search(monkeypatch, [_candidate(0.95, "KEPT")], floor=0.50)

    body = submit_scan(client).json()

    assert [sorted(candidate) for candidate in body] == [
        sorted(["tile_id", "code", "size", "category", "image_id"])
    ]


# --- The env-var override, at the unit level --------------------------------------


def test_the_floor_defaults_to_half_when_the_env_var_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(scan.MATCH_FLOOR_ENV, raising=False)
    try:
        reloaded = importlib.reload(scan)
        assert reloaded.MATCH_FLOOR == pytest.approx(0.50)
        assert reloaded.DEFAULT_MATCH_FLOOR == pytest.approx(0.50)
    finally:
        importlib.reload(scan)


@pytest.mark.parametrize("raw", ["0.8", "-1.0", "1.0", "0"])
def test_a_valid_floor_is_read_once_at_import(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    """Both ends of the cosine range are legal values, not merely the middle.

    `-1.0` is "no bar at all" stated explicitly and `1.0` is "only an exact
    match", and an operator fitting the bar against real photos may reasonably
    walk it to either end — the guard below rejects what is *outside* the
    range, not the range's own endpoints.
    """
    monkeypatch.setenv(scan.MATCH_FLOOR_ENV, raw)
    try:
        assert importlib.reload(scan).MATCH_FLOOR == pytest.approx(float(raw))
    finally:
        monkeypatch.delenv(scan.MATCH_FLOOR_ENV, raising=False)
        importlib.reload(scan)


@pytest.mark.parametrize("raw", ["not-a-number", "", "nan", "inf", "-inf", "1.01", "-1.01", "50"])
def test_an_invalid_floor_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    """`anomaly._read_multiplier`'s shape, with this parameter's own boundaries.

    **`"1.01"` and `"50"` are the dangerous ones, not filler.** A score is a
    cosine similarity and cannot exceed `1.0`, so any bar above it is one no
    Candidate can ever clear: every scan would answer "No confident match" and
    the product would stop working from a single stray digit. `"50"` is the
    specific typo this parameter invites — the bar is spoken about as "50%",
    and writing that as `50` rather than `0.50` must not silently disable
    matching. `"-1.01"` fails for the mirror reason: below the range the bar
    quietly stops existing.
    """
    monkeypatch.setenv(scan.MATCH_FLOOR_ENV, raw)
    try:
        with caplog.at_level(logging.WARNING, logger="rocell.api.scan"):
            reloaded = importlib.reload(scan)

        assert reloaded.MATCH_FLOOR == reloaded.DEFAULT_MATCH_FLOOR
        assert any(repr(raw) in record.getMessage() for record in caplog.records)
    finally:
        monkeypatch.delenv(scan.MATCH_FLOOR_ENV, raising=False)
        importlib.reload(scan)
