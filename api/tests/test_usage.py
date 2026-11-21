import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.app.contracts import Case
from api.app.sample import ORDER
from api.app.store import Store, save_case
from api.app.usage import COMPETITION_ZONE, consume_case_quota
from api.main import create_app

CASE = {"order_id": ORDER.id, "claim_type": "wrong_item"}
HEADERS = {"X-Demo-Passcode": "usage-test"}


def test_per_ip_limit_is_atomic_and_survives_restart_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "usage-test")
    peer = "192.0.2.84"
    with TestClient(create_app(tmp_path), headers=HEADERS, client=(peer, 4000)) as session:

        def submit(i: int) -> httpx.Response:
            return session.post(
                "/api/cases", json=CASE, headers={"X-Forwarded-For": f"192.0.2.{i}"}
            )

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(submit, range(12)))
        assert sorted(response.status_code for response in results) == [201] * 10 + [429] * 2
        denied = next(response for response in results if response.status_code == 429)
        assert 0 < int(denied.headers["Retry-After"]) <= 86400
        assert "IP" in denied.json()["detail"]
        created = next(response for response in results if response.status_code == 201)
        assert session.delete("/api/cases/" + created.json()["id"]).status_code == 204

    with TestClient(
        create_app(tmp_path), headers=HEADERS, client=("::ffff:" + peer, 4001)
    ) as session:
        assert session.post("/api/cases", json=CASE).status_code == 429
        assert len(session.get("/api/my/cases").json()) == 10  # Nine remaining plus the seed.

    with Store(tmp_path).connection() as db:
        assert db.execute("SELECT total FROM usage").fetchall() == [(10,)]
        assert db.execute("SELECT total, length(peer_digest) FROM daily_ip_usage").fetchall() == [
            (10, 32)
        ]
        assert peer not in "\n".join(db.iterdump())


def test_fifty_case_limit_across_distinct_peers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "usage-test")
    app = create_app(tmp_path)

    async def submit_peer(i: int) -> list[int]:
        transport = httpx.ASGITransport(app=app, client=(f"192.0.2.{i}", 1234))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=HEADERS
        ) as session:
            # Nine requests each across six peers. Only the global limit can reject one.
            return [(await session.post("/api/cases", json=CASE)).status_code for _ in range(9)]

    async def submit_all() -> list[list[int]]:
        return await asyncio.gather(*(submit_peer(i) for i in range(6)))

    with TestClient(app, headers=HEADERS) as session:
        results = asyncio.run(submit_all())
        assert sorted(status for peer in results for status in peer) == [201] * 50 + [429] * 4
        assert len(session.get("/api/my/cases").json()) == 51
    with Store(tmp_path).connection() as db:
        assert db.execute("SELECT total FROM usage").fetchone() == (50,)
        assert db.execute("SELECT SUM(total) FROM daily_ip_usage").fetchone() == (50,)


def test_failed_create_can_be_retried_without_spending_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "usage-test")
    store = Store(tmp_path)
    with TestClient(
        create_app(tmp_path), headers=HEADERS, raise_server_exceptions=False
    ) as session:
        assert session.post("/api/cases", json={**CASE, "order_id": "missing"}).status_code == 404
        with store.transaction() as db:
            db.execute(
                "CREATE TRIGGER fail_write BEFORE INSERT ON cases BEGIN SELECT RAISE(ABORT, 'failed'); END"
            )
        assert session.post("/api/cases", json=CASE).status_code == 500
        with store.transaction() as db:
            assert db.execute("SELECT total FROM usage").fetchone() == (0,)
            assert db.execute("SELECT COUNT(*) FROM daily_ip_usage").fetchone() == (0,)
            db.execute("DROP TRIGGER fail_write")
        assert session.post("/api/cases", json=CASE).status_code == 201
        with store.connection() as db:
            assert db.execute("SELECT total FROM usage").fetchone() == (1,)


def test_quota_resets_at_bangkok_midnight(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.initialize()
    tomorrow = datetime.now(COMPETITION_ZONE).date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, datetime.min.time(), COMPETITION_ZONE).astimezone(UTC)
    before = midnight - timedelta(microseconds=1)
    with store.transaction() as db:
        for _ in range(10):
            consume_case_quota(db, "2001:db8::1", before)
        old_digest = db.execute("SELECT peer_digest FROM daily_ip_usage").fetchone()[0]
    with pytest.raises(HTTPException) as rejected, store.transaction() as db:
        consume_case_quota(db, "2001:0db8:0:0:0:0:0:1", before)
    assert rejected.value.headers == {"Retry-After": "1"}
    with store.transaction() as db:
        consume_case_quota(db, "2001:db8::1", midnight)
        day, total, digest = db.execute(
            "SELECT day, total, peer_digest FROM daily_ip_usage"
        ).fetchone()
        assert (day, total) == (tomorrow.isoformat(), 1)
        assert digest != old_digest
        assert db.execute("SELECT COUNT(*) FROM daily_ip_usage").fetchone() == (1,)


def test_upgrade_counts_existing_cases_once_without_assigning_ips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "usage-test")
    store = Store(tmp_path)
    new = Case(
        id="UJ-TODAY", **CASE, description="", status="awaiting_video", created_at=datetime.now(UTC)
    )
    with store.transaction() as db:
        # Original unversioned schema from before daily limits and generated columns.
        db.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        save_case(db, new)
        save_case(db, new.model_copy(update={"id": "UJ-SAMPLE"}))
        save_case(
            db,
            new.model_copy(
                update={"id": "UJ-PAST", "created_at": new.created_at - timedelta(days=2)}
            ),
        )
    for _ in range(2):
        with TestClient(create_app(tmp_path)), store.connection() as db:
            assert db.execute("SELECT total FROM usage").fetchone() == (1,)
            assert db.execute("SELECT COUNT(*) FROM daily_ip_usage").fetchone() == (0,)
