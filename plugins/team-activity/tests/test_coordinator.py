import importlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

coordinator = importlib.import_module("plugins.team-activity.coordinator")
TEAM = {"Authorization": "Bearer test-only"}
A = {**TEAM, "X-Activity-Session": "a" * 64}
B = {**TEAM, "X-Activity-Session": "b" * 64}


def task(name: str, path: str) -> dict:
    return {
        "member": name,
        "agent": "Codex",
        "branch": f"{name}/task",
        "task": path,
        "paths": [path],
    }


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TEAM_ACTIVITY_TOKEN", "test-only")
    monkeypatch.setenv("TEAM_ACTIVITY_DB", str(tmp_path / "activity.sqlite3"))
    return TestClient(coordinator.create_app())


def test_claims_are_atomic_and_retriable(client: TestClient) -> None:
    def claim(item: tuple[dict, str]) -> int:
        headers, name = item
        return client.put("/claim", headers=headers, json=task(name, "api")).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, [(A, "Ama"), (B, "Game")])) == [200, 409]
    winner = client.get("/activity", headers=TEAM).json()[0]["member"]
    first, second = (A, B) if winner == "Ama" else (B, A)
    assert client.put("/claim", headers=first, json=task("First", "./api/")).status_code == 200
    assert client.put("/claim", headers=second, json=task("Second", "api2")).status_code == 200
    assert (
        client.put("/claim", headers=second, json=task("Second", "API/main.py")).status_code == 409
    )
    assert {a["paths"][0] for a in client.get("/activity", headers=TEAM).json()} == {"api", "api2"}
    assert client.delete("/claim", headers=first).status_code == 204
    assert (
        client.put("/claim", headers=second, json=task("Second", "api/main.py")).status_code == 200
    )
    assert client.put("/claim", headers=first, json=task("First", "api")).status_code == 409


def test_lifecycle_and_restart(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coordinator, "LEASE_SECONDS", 1)
    result = client.put("/claim", headers=A, json=task("Thant", "api")).json()
    clock = result["expires_at"]
    monkeypatch.setattr(coordinator.time, "time", lambda: clock - 0.5)
    monkeypatch.setattr(coordinator, "LEASE_SECONDS", 900)
    renewed = client.post("/heartbeat", headers=A).json()
    assert renewed["expires_at"] > clock
    client = TestClient(coordinator.create_app())
    assert len(client.get("/activity", headers=TEAM).json()) == 1
    monkeypatch.setattr(coordinator.time, "time", lambda: renewed["expires_at"])
    assert client.get("/activity", headers=TEAM).json() == []
    assert client.post("/heartbeat", headers=A).status_code == 404
    assert client.put("/claim", headers=B, json=task("Ama", "api")).status_code == 200
    assert client.delete("/claim", headers=A).status_code == 204
    assert client.get("/activity", headers=TEAM).json()[0]["member"] == "Ama"


def test_authentication_and_path_validation(client: TestClient) -> None:
    assert client.get("/activity").status_code == 401
    assert client.put("/claim", headers=TEAM, json=task("Ama", "api")).status_code == 422
    for path in ["../api", "/api", "api/*", "C:\\Users"]:
        assert client.put("/claim", headers=A, json=task("Ama", path)).status_code == 422
