from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app.sample import ORDER
from api.app.store import Store, consume_case_quota
from api.main import create_app

BODY = {"order_id": ORDER.id, "claim_type": "damaged", "description": "Damaged tee"}
HEADERS = {"X-Demo-Passcode": "quota-test"}


def test_per_ip_cap_survives_deletion_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "quota-test")
    with TestClient(create_app(tmp_path), headers=HEADERS) as client:
        assert client.post("/api/cases", json={**BODY, "order_id": "missing"}).status_code == 404

        def submit(index: int) -> tuple[int, str | None]:
            # Caller-supplied forwarding headers do not create additional quota.
            headers = {"X-Forwarded-For": f"192.0.2.{index}"}
            response = client.post("/api/cases", headers=headers, json=BODY)
            return response.status_code, response.json().get("id")

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(12)))
        assert Counter(code for code, _ in results) == {201: 10, 429: 2}
        case_id = next(case_id for code, case_id in results if code == 201)
        assert client.delete(f"/api/cases/{case_id}").status_code == 204
    with TestClient(create_app(tmp_path), headers=HEADERS) as restarted:
        assert restarted.post("/api/cases", json=BODY).status_code == 429


def test_competing_creations_respect_global_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "quota-test")
    day = datetime.now(UTC).date()
    with TestClient(create_app(tmp_path), headers=HEADERS) as client:
        with Store(tmp_path).transaction() as db:
            for index in range(49):
                consume_case_quota(db, day, f"192.0.2.{index // 10}")
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(
                pool.map(lambda _: client.post("/api/cases", json=BODY).status_code, (1, 2))
            )
        assert sorted(codes) == [201, 429]


def test_prior_day_and_rolled_back_attempts_do_not_consume_quota(tmp_path: Path) -> None:
    day = datetime.now(UTC).date()
    store = Store(tmp_path)
    store.initialize()
    with store.transaction() as db:
        for _ in range(10):
            consume_case_quota(db, day - timedelta(days=1), "192.0.2.1")
    with store.transaction() as db:
        consume_case_quota(db, day, "192.0.2.1")
        db.rollback()
    with store.transaction() as db:
        for _ in range(10):
            consume_case_quota(db, day, "192.0.2.1")
        assert db.execute("SELECT created FROM daily_case_usage").fetchall() == [(10,)]


def test_upgrade_counts_existing_cases_once_in_global_limit(tmp_path: Path) -> None:
    import json

    store = Store(tmp_path)
    now = datetime.now(UTC)
    # This is the creation timestamp used by the previous SQLite schema.
    with store.transaction() as db:
        db.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        db.executemany(
            "INSERT INTO cases VALUES(?, ?)",
            [
                (case_id, json.dumps({"created_at": created.isoformat()}))
                for case_id, created in [
                    ("UJ-existing", now),
                    ("UJ-SAMPLE", now),
                    ("UJ-yesterday", now - timedelta(days=1)),
                ]
            ],
        )
    store.initialize()
    store.initialize()
    with store.connection() as db:
        assert db.execute("SELECT SUM(created) FROM daily_case_usage").fetchone() == (1,)
