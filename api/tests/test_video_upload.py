from pathlib import Path
import subprocess
from threading import Event

import pytest
from fastapi.testclient import TestClient

from api.app.contracts import Verdict
from api.app.fake import FakeJudge
from api.main import create_app


def test_video_survives_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recording = tmp_path / "source.mp4"
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
            str(recording),
        ],
        check=True,
    )
    payload = recording.read_bytes()
    entered, release = Event(), Event()

    class PausedJudge(FakeJudge):
        def run(self, case_dir: Path) -> Verdict:
            assert (case_dir / "video.mp4").read_bytes() == payload
            entered.set()
            assert release.wait(timeout=10)
            return super().run(case_dir)

    monkeypatch.setenv("DEMO_PASSCODE", "test")
    monkeypatch.setenv("SHOP_PASSCODE", "shop-test")
    headers = {"X-Demo-Passcode": "test", "X-Shop-Passcode": "shop-test"}
    db_dir = tmp_path / "data"
    with TestClient(create_app(db_dir, PausedJudge()), headers=headers) as client:
        case_id = client.post(
            "/api/cases", json={"order_id": "UJ-48213", "claim_type": "damaged"}
        ).json()["id"]
        case_url = f"/api/cases/{case_id}"
        video_url = case_url + "/video"
        files = {"video": ("video.mp4", payload, "video/mp4")}
        try:
            result = client.post(video_url, files=files)
            assert result.status_code == 202, result.text
            assert result.json()["warnings"]
            assert entered.wait(timeout=5)
            assert client.get(case_url).json() == {
                "id": case_id,
                "status": "checking",
                "note_for_buyer": None,
            }
            assert client.post(video_url, files=files).status_code == 409
            assert client.delete(case_url).status_code == 409
        finally:
            release.set()
        events = client.get(case_url + "/events")
        assert events.status_code == 200
        assert "event: done" in events.text
        assert "confidence" not in events.text

    with TestClient(create_app(db_dir), headers=headers) as client:
        shop = client.get(f"/api/shop/cases/{case_id}").json()
        assert shop["status"] == "ready" and shop["verdict"]["case_id"] == case_id
        video = client.get(shop["video_url"])
        assert video.content == payload and video.headers["content-type"] == "video/mp4"
        assert client.delete(case_url).status_code == 204
        assert client.get(shop["video_url"]).status_code == 404


def test_intake_concurrency_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    from api.app import uploads

    started, release = Event(), Event()
    lock = Lock()
    clients_ready = Barrier(3)
    active = peak = 0

    def paused_intake(*args: object) -> list[str]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                started.set()
        try:
            assert release.wait(5)
        finally:
            with lock:
                active -= 1
        return []

    monkeypatch.setattr(uploads, "stage_and_submit", paused_intake)
    monkeypatch.setenv("DEMO_PASSCODE", "test")
    monkeypatch.setenv("SHOP_PASSCODE", "shop-test")
    with TestClient(
        create_app(tmp_path), headers={"X-Demo-Passcode": "test", "X-Shop-Passcode": "shop-test"}
    ) as client:
        case = client.post(
            "/api/cases", json={"order_id": "UJ-48213", "claim_type": "damaged"}
        ).json()

        def submit() -> int:
            clients_ready.wait(5)
            return client.post(
                f"/api/cases/{case['id']}/video", files={"video": ("clip.mp4", b"test")}
            ).status_code

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = [pool.submit(submit) for _ in range(3)]
            try:
                assert started.wait(5)
            finally:
                release.set()
            assert [r.result() for r in results] == [202, 202, 202]
        assert peak == 2
