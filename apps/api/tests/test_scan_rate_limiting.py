"""Story 3.6 — FR-23's per-user scan throttle, AD-8's counter shape again.

Driven against a real PostgreSQL for the same reason `test_login_throttling.py`
is: `scan_throttle.check_and_record` is one atomic `INSERT ... ON CONFLICT DO
UPDATE ... RETURNING`, and the only honest way to prove a concurrent burst
never loses an update is to run it against a real row lock, not a mock.

`sign_in`, `submit_scan`, `jpeg_bytes` and `a_tile_photograph` are restated
here rather than imported, `test_scan_submission.py`'s own established
convention (3.5's Design Notes) — this suite's own test file restates the
helpers it needs locally.
"""

from __future__ import annotations

import importlib
import io
import logging
import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import numpy as np
import psycopg
import pytest
from api import anomaly, scan_throttle
from fastapi.testclient import TestClient
from PIL import Image
from psycopg.rows import dict_row

MakeUser = Callable[..., Any]

LOGIN = "/auth/login"
SCANS = "/scans"


def a_tile_photograph(seed: int = 5, size: tuple[int, int] = (320, 320)) -> Image.Image:
    """A textured patch — `test_scan_submission.py`'s own helper, unchanged."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def jpeg_bytes(image: Image.Image | None = None) -> bytes:
    buf = io.BytesIO()
    (image or a_tile_photograph()).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


def submit_scan(
    client: TestClient,
    *,
    crop_x: float = 0.1,
    crop_y: float = 0.1,
    crop_width: float = 0.8,
    crop_height: float = 0.8,
    image: tuple[str, bytes, str] | None = None,
) -> Any:
    """`POST /scans` as multipart, `test_scan_submission.py`'s own shape."""
    data = {
        "crop_x": crop_x,
        "crop_y": crop_y,
        "crop_width": crop_width,
        "crop_height": crop_height,
    }
    files = [("image", image or ("scan.jpg", jpeg_bytes(), "image/jpeg"))]
    return client.post(SCANS, data=data, files=files)


def _scan_rows(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return list(conn.execute("SELECT user_id FROM scan ORDER BY created_at").fetchall())


def _rate_limit_row(conn: psycopg.Connection, user_id: Any) -> dict[str, Any] | None:
    return conn.execute("SELECT * FROM scan_rate_limit WHERE user_id = %s", (user_id,)).fetchone()


@pytest.fixture
def low_limit(monkeypatch: pytest.MonkeyPatch) -> int:
    """A rate low enough to reach in a handful of requests, `test_login_throttling.py`'s
    own `monkeypatch.setattr(throttle, "CONSTANT", value)` technique — reused
    here against `scan_throttle` rather than an env-var round trip, because
    `check_and_record` reads the module-level constant at call time, not as a
    default argument.
    """
    limit = 2
    monkeypatch.setattr(scan_throttle, "SCAN_RATE_LIMIT", limit)
    return limit


# --- The Nth submission is throttled -----------------------------------------


def test_a_low_limit_throttles_the_submission_past_it(
    client: TestClient, make_user: MakeUser, low_limit: int
) -> None:
    account = make_user()
    sign_in(client, account)

    for expected in range(1, low_limit + 1):
        response = submit_scan(client)
        assert response.status_code == 200, (expected, response.text)

    over_limit = submit_scan(client)

    assert over_limit.status_code == 429
    body = over_limit.json()
    assert body["error"]["code"] == "scan_rate_limited"
    assert over_limit.headers["cache-control"] == "no-store"
    # EXPERIENCE.md line 89: a plain sentence, no countdown, and no
    # `Retry-After` — unlike the login lockout, nothing here carries timing.
    assert "retry-after" not in {key.lower() for key in over_limit.headers}
    assert not any(character.isdigit() for character in body["error"]["message"])


def test_a_throttled_submission_is_still_counted_toward_the_anomaly_baseline(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    low_limit: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 3.6's throttle and Story 3.7's anomaly flag are independent
    checks on the same request (epic-3-context.md: "a burst can trip one
    without the other") — this is the one test proving it for real, against
    the actual over-the-limit response, rather than trusting that a future
    refactor never moves the throttle's early return above the anomaly
    check. `anomaly.check_and_flag` is forced `True` rather than driven past
    a real deviation, `test_anomaly_flagging.py`'s own reason: that module is
    covered in isolation there.
    """
    monkeypatch.setattr(anomaly, "check_and_flag", lambda *_args, **_kwargs: True)
    account = make_user()
    sign_in(client, account)
    for _ in range(low_limit):
        assert submit_scan(client).status_code == 200

    over_limit = submit_scan(client)

    assert over_limit.status_code == 429
    assert over_limit.json()["error"]["code"] == "scan_rate_limited"
    rows = conn.execute(
        "SELECT actor_user_id, actor_email FROM audit_log WHERE action = %s",
        ("scan_volume_anomaly_flagged",),
    ).fetchall()
    # One flag row per submission this fixture forced `True` for, including
    # the throttled one itself — the throttled burst is still counted toward
    # the volume baseline, not silently dropped because it was also refused.
    assert len(rows) == low_limit + 1
    assert all(row["actor_user_id"] == account.id for row in rows)
    assert all(row["actor_email"] == account.email for row in rows)


def test_a_throttled_submission_persists_no_scan_row(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, low_limit: int
) -> None:
    account = make_user()
    sign_in(client, account)
    for _ in range(low_limit):
        assert submit_scan(client).status_code == 200

    response = submit_scan(client)

    assert response.status_code == 429
    # The over-limit submission itself wrote no `scan` row — every earlier,
    # accepted submission against an empty catalogue did (Story 3.5), so the
    # count below is exactly `low_limit`, not `low_limit` plus the refusal.
    assert len(_scan_rows(conn)) == low_limit


def test_a_throttled_caller_keeps_being_refused_and_keeps_being_counted(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, low_limit: int
) -> None:
    account = make_user()
    sign_in(client, account)
    for _ in range(low_limit):
        assert submit_scan(client).status_code == 200

    for expected in range(low_limit + 1, low_limit + 4):
        response = submit_scan(client)
        assert response.status_code == 429, expected
        row = _rate_limit_row(conn, account.id)
        assert row is not None
        assert row["submission_count"] == expected


def test_a_submission_refused_for_a_later_reason_still_counts(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, low_limit: int
) -> None:
    """The throttle check runs before the crop rectangle (AD-16's fixed order),
    so a submission refused for that later reason must still increment the
    counter — this is what stops a future refactor that moves the throttle
    check later from silently letting refused requests bypass it for free.

    Driven with an out-of-bounds crop rectangle. It used to be driven by a
    flat photograph failing FR-9's blur gate, deliberately, because that
    refusal landed *after* the crop succeeded and so was the harder case to
    get right. That gate has since been removed, and no refusal after the
    crop is reachable without breaking the model, so the rectangle is what is
    left to assert with.
    """
    account = make_user()
    sign_in(client, account)

    for expected in range(1, low_limit + 1):
        response = submit_scan(client, crop_x=0.9, crop_width=0.5)
        assert response.status_code == 422, expected
        assert response.json()["error"]["code"] == "invalid_crop_rect"
        row = _rate_limit_row(conn, account.id)
        assert row is not None
        assert row["submission_count"] == expected

    # The counter is now at `low_limit`, purely from refusals and with no
    # successful scan ever recorded — so an otherwise-valid submission is
    # itself throttled, proving the earlier refusals were not free.
    assert submit_scan(client).status_code == 429
    assert _scan_rows(conn) == []


# --- The window resets --------------------------------------------------------


def test_a_stale_window_resets_and_lets_a_throttled_caller_back_in(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, low_limit: int
) -> None:
    account = make_user()
    sign_in(client, account)
    for _ in range(low_limit):
        assert submit_scan(client).status_code == 200
    assert submit_scan(client).status_code == 429

    # Backdated directly in the database — `test_login_throttling.py`'s own
    # `test_a_stale_run_resets` technique — rather than a real sleep, and well
    # past `SCAN_RATE_LIMIT_WINDOW` whatever it is configured to.
    conn.execute(
        "UPDATE scan_rate_limit SET window_started_at = now() - %s WHERE user_id = %s",
        (timedelta(seconds=scan_throttle.SCAN_RATE_LIMIT_WINDOW + 60), account.id),
    )

    response = submit_scan(client)

    assert response.status_code == 200, response.text
    row = _rate_limit_row(conn, account.id)
    assert row is not None
    assert row["submission_count"] == 1


# --- The limit is per user -----------------------------------------------------


def test_one_users_throttling_does_not_affect_another(
    client: TestClient, make_user: MakeUser, low_limit: int
) -> None:
    throttled = make_user()
    sign_in(client, throttled)
    for _ in range(low_limit):
        assert submit_scan(client).status_code == 200
    assert submit_scan(client).status_code == 429

    other = make_user()
    sign_in(client, other)

    assert submit_scan(client).status_code == 200


# --- The env-var override, at the unit level ----------------------------------


def test_the_rate_and_window_env_vars_are_read_once_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(scan_throttle.SCAN_RATE_LIMIT_ENV, "7")
    monkeypatch.setenv(scan_throttle.SCAN_RATE_LIMIT_WINDOW_ENV, "12.5")
    try:
        reloaded = importlib.reload(scan_throttle)
        assert reloaded.SCAN_RATE_LIMIT == 7
        assert reloaded.SCAN_RATE_LIMIT_WINDOW == pytest.approx(12.5)
    finally:
        monkeypatch.delenv(scan_throttle.SCAN_RATE_LIMIT_ENV, raising=False)
        monkeypatch.delenv(scan_throttle.SCAN_RATE_LIMIT_WINDOW_ENV, raising=False)
        importlib.reload(scan_throttle)


@pytest.mark.parametrize("raw", ["not-a-number", "", "0", "-5"])
def test_an_invalid_rate_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    """Unparseable and non-positive values must both fall back.

    `"0"` and `"-5"` parse cleanly as ordinary Python ints — `int()` raises
    nothing for either — so without its own lower-bound check `_read_rate_limit`
    would hand `check_and_record` a limit that refuses every user's very first
    submission, silently disabling scanning product-wide from a plain operator
    typo with no warning logged anywhere.
    """
    monkeypatch.setenv(scan_throttle.SCAN_RATE_LIMIT_ENV, raw)
    try:
        with caplog.at_level(logging.WARNING, logger="rocell.api.scan_throttle"):
            reloaded = importlib.reload(scan_throttle)

        assert reloaded.SCAN_RATE_LIMIT == reloaded.DEFAULT_SCAN_RATE_LIMIT
        assert any(raw in record.getMessage() for record in caplog.records)
    finally:
        monkeypatch.delenv(scan_throttle.SCAN_RATE_LIMIT_ENV, raising=False)
        importlib.reload(scan_throttle)


@pytest.mark.parametrize("raw", ["not-a-number", "nan", "inf", "-inf", "-5", "1e20"])
def test_an_invalid_window_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    """Unparseable,
    non-finite and negative values must all fall back rather than reach the
    SQL below with a window that could never resolve.

    `"1e20"` parses to a finite, non-negative `float` with no error at all —
    it is only rejected because `timedelta(seconds=1e20)` itself overflows.
    Without that guard, `check_and_record` would raise an uncaught
    `OverflowError` on every `POST /scans` for as long as the variable stayed
    set, turning a typo into an outage rather than a logged fallback.
    """
    monkeypatch.setenv(scan_throttle.SCAN_RATE_LIMIT_WINDOW_ENV, raw)
    try:
        with caplog.at_level(logging.WARNING, logger="rocell.api.scan_throttle"):
            reloaded = importlib.reload(scan_throttle)

        assert reloaded.SCAN_RATE_LIMIT_WINDOW == reloaded.DEFAULT_SCAN_RATE_LIMIT_WINDOW
        assert any(raw in record.getMessage() for record in caplog.records)
    finally:
        monkeypatch.delenv(scan_throttle.SCAN_RATE_LIMIT_WINDOW_ENV, raising=False)
        importlib.reload(scan_throttle)


def test_a_missing_env_var_uses_the_documented_default() -> None:
    assert scan_throttle.SCAN_RATE_LIMIT == scan_throttle.DEFAULT_SCAN_RATE_LIMIT
    assert scan_throttle.SCAN_RATE_LIMIT_WINDOW == scan_throttle.DEFAULT_SCAN_RATE_LIMIT_WINDOW


# --- AD-8's concurrency property ----------------------------------------------


def test_the_counter_survives_being_driven_from_two_connections(
    migrated_url: str, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    """One atomic increment-and-check, not a read followed by a write.

    `test_login_throttling.py`'s own concurrency test, restated against
    `scan_throttle.check_and_record` directly: twenty increments arriving on
    two connections at once must leave twenty, and a `SELECT` followed by an
    `UPDATE` would lose some of them without raising anything.
    """
    account = make_user()
    per_thread = 10
    ready = threading.Barrier(2)
    failures: list[BaseException] = []

    def drive() -> None:
        try:
            with psycopg.connect(
                migrated_url, autocommit=True, row_factory=dict_row
            ) as thread_conn:
                ready.wait(timeout=30)
                for _ in range(per_thread):
                    scan_throttle.check_and_record(thread_conn, account.id)
        except BaseException as failure:  # noqa: BLE001 - re-raised on the main thread
            failures.append(failure)
            ready.abort()

    threads = [threading.Thread(target=drive) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    if failures:
        raise failures[0]

    row = _rate_limit_row(conn, account.id)
    assert row is not None
    assert row["submission_count"] == per_thread * 2
