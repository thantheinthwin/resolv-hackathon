"""Exercise uploads, private reviews, judging and decisions with an offline model transport."""

import base64
import json
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from typing import cast

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app.contracts import Case, Verdict
from api.app.judging import CaseJudge
from api.app.sample import ORDER
from api.app.store import Store
from api.main import create_app
from judge import ReviewRequest
from judge.opening_review import OpeningReviewRequest, OpeningReviewSelection


def recording(path: Path, *, cut: bool) -> bytes:
    """A changing sharp pattern with an optional abrupt light change at four seconds."""
    rng = np.random.default_rng(12)
    checker = np.indices((96, 96)).sum(axis=0) % 2
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 2, (96, 96))
    try:
        assert writer.isOpened()
        for second in range(7):
            pattern = cv2.resize(
                rng.integers(0, 25, (8, 8), dtype=np.uint8),
                (96, 96),
                interpolation=cv2.INTER_NEAREST,
            )
            offset = 180 if cut and second >= 4 else 85
            pixels = (checker * 50 + offset + pattern).astype(np.uint8)
            frame = cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR)
            writer.write(frame)
            writer.write(frame)
    finally:
        writer.release()
    return path.read_bytes()


class ScenarioResponses:
    """Only the external model responses are simulated. Media processing runs locally."""

    def __init__(self, wrong_colour: bool) -> None:
        self.wrong_colour = wrong_colour
        self.calls: list[str] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        schema = cast(type, kwargs["text_format"]).__name__
        self.calls.append(schema)
        result: dict[str, object]
        if schema == "VisionObservation":
            colour = "navy" if self.wrong_colour else "black"
            result = {
                "status": "observed",
                "findings": [{"t": 2, "category": "color", "value": colour, "confidence": 0.99}],
                "note_en": colour,
            }
        elif schema == "MatchResponse":
            messages = cast(list[dict[str, list[dict[str, str]]]], kwargs["input"])
            payload = messages[1]["content"][0]["text"]
            check = json.loads(payload.splitlines()[0])["check"]
            mismatch = self.wrong_colour and check == "variant"
            result = {
                "status": "flag" if mismatch else "pass",
                "confidence": 0.98,
                "findings": [{"t": 2, "note_en": "Navy tee.", "note_th": "เสื้อสีกรมท่า"}]
                if mismatch
                else [],
                "note_en": "Compared with the listing.",
            }
        else:
            assert schema == "ReasonSelection"
            result = {"finding_id": 0}
        return SimpleNamespace(output_parsed=result)


def await_verdict(
    client: TestClient,
    case_id: str,
    shop: dict[str, str],
    model: ScenarioResponses,
    prepared: bool,
) -> tuple[Case, dict[str, bytes]]:
    detail = f"/api/shop/cases/{case_id}"
    images: dict[str, bytes] = {}
    stages: set[str] = set()
    deadline = monotonic() + 45
    while monotonic() < deadline:
        case = client.get(detail, headers=shop).json()
        assert case["status"] != "failed"
        if case["status"] == "ready":
            if not prepared:
                assert {"visual", "observation"} <= stages
            return Case.model_validate(case), images
        review = client.get(detail + "/review", headers=shop)
        if review.status_code == 404:
            sleep(0.025)
            continue
        assert not prepared, "Uploading the pre-reviewed clip unexpectedly started a second review."
        assert review.status_code == 200, review.text
        pending = review.json()
        stage = pending["stage"]
        stages.add(stage)
        approval = {field: pending[field] for field in ("upload_id", "stage", "fingerprint")}
        if stage == "visual":
            assert not model.calls
            images = {
                img["name"]: base64.b64decode(img["jpeg_base64"]) for img in pending["images"]
            }
        response = client.post(detail + "/review/approve", headers=shop, json=approval)
        assert response.status_code == 204, response.text
    pytest.fail(f"Case did not finish after review stages {stages}")


@pytest.mark.parametrize("expected", ["buyer_right", "seller_right", "needs_human"])
def test_uploaded_case_reaches_buyer_reply(
    expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "test-demo")
    monkeypatch.setenv("SHOP_PASSCODE", "test-shop")
    shop = {"X-Shop-Passcode": "test-shop"}
    data = tmp_path / "data"
    model = ScenarioResponses(wrong_colour=expected != "seller_right")
    worker = CaseJudge(Store(data), model="offline-test", client=SimpleNamespace(responses=model))
    app = create_app(data, judge=worker)
    reviewed_images: dict[str, bytes] = {}

    def review(request: ReviewRequest) -> bool:
        reviewed_images.update(request.images)
        return True

    def inspect_opening(request: OpeningReviewRequest) -> OpeningReviewSelection:
        assert request.frames[0].timestamp_seconds == 0
        return OpeningReviewSelection(frame_number=1, seal_state="intact")

    with TestClient(app, headers={"X-Demo-Passcode": "test-demo"}) as client:
        created = client.post("/api/cases", json={"order_id": ORDER.id, "claim_type": "wrong_item"})
        assert created.status_code == 201
        case_id = created.json()["id"]
        route = f"/api/cases/{case_id}"
        shop_route = f"/api/shop/cases/{case_id}"
        clip = recording(tmp_path / "input.mp4", cut=expected == "needs_human")
        if expected != "needs_human":
            worker.prepare(case_id, tmp_path / "input.mp4", review, opening_review=inspect_opening)
        response = client.post(route + "/video", files={"video": ("input.mp4", clip, "video/mp4")})
        assert response.status_code == 202, response.text
        assert client.get(shop_route + "/review").status_code in (401, 403)
        case, approved_after_upload = await_verdict(
            client, case_id, shop, model, prepared=expected != "needs_human"
        )
        reviewed_images.update(approved_after_upload)

        folder = data / "cases" / case_id
        verdict = Verdict.model_validate_json((folder / "verdict.json").read_bytes())
        assert verdict == case.verdict
        assert verdict.verdict == expected
        assert model.calls.count("VisionObservation") == 1
        assert model.calls.count("MatchResponse") == 5
        if expected == "needs_human":
            assert [(flag.type, flag.t) for flag in verdict.flags] == [("cut", 4.0)]
        if expected != "seller_right":
            assert [(e.check, e.t) for e in verdict.evidence] == [("variant", 2.0)]
            for asset in (verdict.evidence[0].frame, verdict.evidence[0].listing_photo):
                url = f"{shop_route}/evidence/{asset}"
                assert client.get(url).status_code in (401, 403)
                image = client.get(url, headers=shop)
                assert image.status_code == 200
                assert image.content == reviewed_images[asset]
                assert client.get(f"/api/files/cases/{case_id}/{asset}").status_code in (401, 403)

        events = client.get(route + "/events")
        assert events.headers["content-type"].startswith("text/event-stream")
        progress = [
            json.loads(line.removeprefix("data: "))
            for line in events.text.splitlines()
            if line.startswith("data: ")
        ]
        assert progress[-1]["event"] == "done"
        finished = {event["step"] for event in progress if event["event"] == "finished"}
        if expected == "needs_human":
            assert {step.name for step in verdict.steps} <= finished
        assert client.get(route).json() == {
            "id": case_id,
            "status": "with_shop",
            "note_for_buyer": None,
        }
        decision = {
            "choice": "agree" if verdict.display == "clear" else "side_buyer",
            "note_for_buyer": "Reviewed.",
        }
        assert client.post(shop_route + "/decision", headers=shop, json=decision).status_code == 200
        assert client.get(route).json() == {
            "id": case_id,
            "status": "replied",
            "note_for_buyer": "Reviewed.",
        }
        if expected == "needs_human":
            assert (folder / ".judge-cache").is_dir()
        assert client.delete(route).status_code == 204
        assert client.get(route).status_code == 404
        assert not folder.exists()
        assert not (data / ".judge-reviews" / case_id).exists()
