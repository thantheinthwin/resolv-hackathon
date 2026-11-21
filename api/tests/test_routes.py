from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app.contracts import Verdict
from api.app import fake
from api.main import create_app


@pytest.mark.parametrize("clear", [False, True])
def test_case_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clear: bool) -> None:
    class UploadJudge:
        def run(self, case_dir: Path) -> Verdict:
            raise AssertionError("Demo startup called the upload judge")

    if clear:
        sample = Verdict.model_validate_json(fake.SAMPLE_VERDICT.read_text())
        clear_fixture = tmp_path / "clear.json"
        clear_fixture.write_text(
            Verdict.model_validate(
                {
                    **sample.model_dump(),
                    "confidence": 0.94,
                    "verdict": "buyer_right",
                    "display": "clear",
                    "leaning": "buyer",
                }
            ).model_dump_json()
        )
        monkeypatch.setattr(fake, "SAMPLE_VERDICT", clear_fixture)

    monkeypatch.setenv("DEMO_PASSCODE", "for-tests")
    headers = {"X-Demo-Passcode": "for-tests"}
    injected_judge = UploadJudge()
    with TestClient(create_app(tmp_path, injected_judge), headers=headers) as client:
        assert client.app.state.judge is injected_judge
        order = client.get("/api/orders").json()[0]
        assert client.get(order["listing"]["photos"][0]).headers["content-type"] == "image/png"
        assert client.get("/api/files/cases/UJ-SAMPLE/verdict.json").status_code == 404
        assert client.get("/api/files/cases.sqlite3").status_code == 404
        case = client.get("/api/shop/cases/UJ-SAMPLE").json()
        saved = Verdict.model_validate_json((tmp_path / "cases/UJ-SAMPLE/verdict.json").read_text())
        assert Verdict.model_validate(case["verdict"]) == saved
        assert saved.display == ("clear" if clear else "unsure")
        before = {"id": "UJ-SAMPLE", "status": "with_shop", "note_for_buyer": None}
        assert client.get("/api/cases/UJ-SAMPLE").json() == before
        assert client.get("/api/my/cases").json() == [before]
        events = client.get("/api/cases/UJ-SAMPLE/events")
        assert events.headers["content-type"].startswith("text/event-stream")
        assert [line for line in events.text.splitlines() if line.startswith("event:")] == [
            "event: started",
            "event: finished",
            "event: done",
        ]
        assert "confidence" not in events.text
        route = "/api/shop/cases/UJ-SAMPLE/decision"
        assert (
            client.post(route, json={"choice": "side_buyer" if clear else "agree"}).status_code
            == 422
        )
        decision = {"choice": "agree" if clear else "side_buyer", "note_for_buyer": "Reviewed."}
        assert client.post(route, json=decision).status_code == 200
        assert client.post(route, json=decision).status_code == 409

    with TestClient(create_app(tmp_path), headers=headers) as client:
        assert client.get("/api/cases/UJ-SAMPLE").json() == {
            "id": "UJ-SAMPLE",
            "status": "replied",
            "note_for_buyer": "Reviewed.",
        }
        assert client.delete("/api/cases/UJ-SAMPLE").status_code == 204
        assert not (tmp_path / "cases/UJ-SAMPLE").exists()
    with TestClient(create_app(tmp_path), headers=headers) as client:
        assert client.get("/api/shop/cases").json() == []


def test_route_contracts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "for-tests")
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/orders").status_code in (401, 403, 422)
        client.headers["X-Demo-Passcode"] = "incorrect"
        assert client.get("/api/orders").status_code == 403
        client.headers["X-Demo-Passcode"] = "for-tests"
        paths = client.get("/openapi.json").json()["paths"]
        assert len(paths) == 14
        order = client.get("/api/orders").json()[0]
        assert client.get("/api/listings").json() == [order["listing"]]
        body = {"order_id": order["id"], "claim_type": "damaged", "description": "Damaged tee"}
        assert client.post("/api/cases", json={**body, "order_id": "missing"}).status_code == 404
        submitted = client.post("/api/cases", json=body)
        assert submitted.status_code == 201
        case = submitted.json()
        assert case["status"] == "awaiting_video"
        buyer_route = f"/api/cases/{case['id']}"
        assert client.get(buyer_route).json()["status"] == "sent"
        assert client.get("/api/shop/cases").json()[0]["display"] == "unsure"
        assert client.post(buyer_route + "/upload-link").status_code == 501
        assert client.get(buyer_route + "/events").status_code == 501
        files = {"video": ("test.mp4", b"sample", "video/mp4")}
        assert client.post(buyer_route + "/video", files=files).status_code == 501
        assert client.post("/api/uploads/sample", files=files).status_code == 501
        assert client.delete(buyer_route).status_code == 204
        assert client.get(buyer_route).status_code == 404
        monkeypatch.delenv("DEMO_PASSCODE")
        assert client.get("/api/orders").status_code == 503


def test_deferred_uploads_never_read_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from collections.abc import Iterator

    def unreadable_body() -> Iterator[bytes]:
        raise AssertionError("A deferred upload must be rejected before reading body bytes")
        yield b""

    monkeypatch.setenv("DEMO_PASSCODE", "for-tests")
    with TestClient(create_app(tmp_path)) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert (
            paths["/api/cases/{id}/video"]["post"]["requestBody"]["content"]["multipart/form-data"][
                "schema"
            ]["properties"]["video"]["format"]
            == "binary"
        )
        for url in ("/api/cases/UJ-SAMPLE/video", "/api/uploads/token", "/api/listings"):
            for passcode, expected in (("invalid", 403), ("for-tests", 501)):
                response = client.post(
                    url,
                    headers={
                        "X-Demo-Passcode": passcode,
                        "Content-Type": "multipart/form-data; boundary=sample",
                    },
                    content=unreadable_body(),
                )
                assert response.status_code == expected


def test_read_during_write_and_competing_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from api.app.store import Store

    monkeypatch.setenv("DEMO_PASSCODE", "for-tests")
    headers = {"X-Demo-Passcode": "for-tests"}
    with TestClient(create_app(tmp_path), headers=headers) as client:
        with Store(tmp_path).transaction() as db:
            db.execute("DELETE FROM cases WHERE id = ?", ("UJ-SAMPLE",))
            assert client.get("/api/cases/UJ-SAMPLE").json()["status"] == "with_shop"
            db.rollback()

        def decide(choice: str) -> int:
            return client.post(
                "/api/shop/cases/UJ-SAMPLE/decision", json={"choice": choice}
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(decide, ["side_seller", "side_buyer"])) == [200, 409]
