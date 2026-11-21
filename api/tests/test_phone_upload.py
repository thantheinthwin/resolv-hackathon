import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from api.app import uploads
from api.app.store import Store
from api.main import create_app
from judge.intake import IntakeResult


@pytest.fixture
def recording(tmp_path: Path) -> bytes:
    path = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=64x64:r=2",
            "-t",
            "5",
            "-vcodec",
            "mpeg4",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


def create_case(client: TestClient) -> str:
    result = client.post("/api/cases", json={"order_id": "UJ-48213", "claim_type": "damaged"})
    assert result.status_code == 201
    return result.json()["id"]


def issue(client: TestClient, case_id: str) -> str:
    result = client.post(f"/api/cases/{case_id}/upload-link")
    assert result.status_code == 200
    link = result.json()
    token = link["token"]
    assert link["url"] == "/upload/" + token
    return token


def test_phone_link_restart_retry_and_single_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording: bytes
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "test")
    headers = {"X-Demo-Passcode": "test"}
    with TestClient(create_app(tmp_path), headers=headers) as client:
        case_id = create_case(client)
        token = issue(client, case_id)
        with Store(tmp_path).connection() as db:
            assert db.execute("SELECT digest FROM upload_links").fetchone() == (
                hashlib.sha256(token.encode()).digest(),
            )

    with TestClient(create_app(tmp_path), headers=headers) as client:
        endpoint = f"/api/uploads/{token}"
        assert client.post(endpoint, files={"video": ("bad.mp4", b"invalid")}).status_code == 422
        result = client.post(endpoint, files={"video": ("phone.mp4", recording, "video/mp4")})
        assert result.status_code == 202
        assert result.json()["id"] == case_id and result.json()["warnings"]
        assert client.post(endpoint).status_code == 404
        assert client.post(f"/api/cases/{case_id}/upload-link").status_code == 409
        assert "event: done" in client.get(f"/api/cases/{case_id}/events").text
        assert client.get(f"/api/cases/{case_id}").json() == {
            "id": case_id,
            "status": "with_shop",
            "note_for_buyer": None,
        }
        case = client.get(f"/api/shop/cases/{case_id}").json()
        assert client.get(case["video_url"]).content == recording
        assert case["verdict"]["case_id"] == case_id


def test_rotating_link_while_phone_intake_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording: bytes
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "test")
    started, release = Event(), Event()
    inspect = uploads.inspect_video

    def pause(path: Path) -> IntakeResult:
        started.set()
        assert release.wait(timeout=5)
        return inspect(path)

    monkeypatch.setattr(uploads, "inspect_video", pause)
    with TestClient(create_app(tmp_path), headers={"X-Demo-Passcode": "test"}) as client:
        case_id = create_case(client)
        first = issue(client, case_id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                client.post, f"/api/uploads/{first}", files={"video": ("phone.mp4", recording)}
            )
            try:
                assert started.wait(timeout=5)
                replacement = issue(client, case_id)
                assert first != replacement
            finally:
                release.set()
            assert result.result(timeout=5).status_code == 404
        assert client.get(f"/api/shop/cases/{case_id}").json()["status"] == "awaiting_video"
        assert client.delete(f"/api/cases/{case_id}").status_code == 204
        assert client.post(f"/api/uploads/{replacement}").status_code == 404


def test_concurrent_token_claims_accept_only_one_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording: bytes
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "test")
    barrier = Barrier(2)
    inspect = uploads.inspect_video

    def wait_for_both(path: Path) -> IntakeResult:
        result = inspect(path)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(uploads, "inspect_video", wait_for_both)
    with TestClient(create_app(tmp_path), headers={"X-Demo-Passcode": "test"}) as client:
        token = issue(client, create_case(client))
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [
                pool.submit(
                    client.post, f"/api/uploads/{token}", files={"video": (name, recording)}
                )
                for name in ("one.mp4", "two.mp4")
            ]
            assert sorted(r.result(timeout=15).status_code for r in requests) == [202, 404]


def test_desktop_upload_revokes_phone_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording: bytes
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "test")
    with TestClient(create_app(tmp_path), headers={"X-Demo-Passcode": "test"}) as client:
        case_id = create_case(client)
        token = issue(client, case_id)
        assert (
            client.post(
                f"/api/cases/{case_id}/video", files={"video": ("desktop.mp4", recording)}
            ).status_code
            == 202
        )
        assert client.post(f"/api/uploads/{token}").status_code == 404
