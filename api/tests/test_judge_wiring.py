import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import judge
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app.contracts import Verdict
from api.app.judging import CaseJudge
from api.app.photo_formats import PHOTO_FORMATS
from api.app.store import Store
from api.main import create_app
from judge import (
    JudgeInputs,
    ReviewRequest,
    ReviewRequired,
    complaint,
    matching,
    reasons,
    text_model,
    vision,
)


def test_reviewed_upload_publishes_grounded_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "test")
    monkeypatch.setenv("OPENAI_MODEL", "mock")
    approvals = []
    calls = []

    class Transport:
        def parse(self, **kwargs: object) -> SimpleNamespace:
            schema = kwargs["text_format"]
            calls.append(schema)
            if schema is vision.VisionObservation:
                assert approvals == ["visual", "visual"]
                answer = {"status": "observed", "findings": [], "note_en": "Visible product."}
            elif schema is matching.MatchResponse:
                answer = {
                    "status": "flag",
                    "confidence": 0.95,
                    "findings": [
                        {"t": 0.0, "note_en": "Visible discrepancy.", "note_th": "พบความแตกต่าง"}
                    ],
                    "note_en": "Compared.",
                }
            elif schema is complaint.ComplaintSelection:
                assert approvals == ["visual", "visual", "complaint"]
                answer = {"confidence": 0.9, "allegations": []}
            else:
                assert schema is reasons.ReasonSelection
                assert approvals == ["visual", "visual", "complaint", "reason"]
                answer = {"finding_id": 0}
            return SimpleNamespace(output_parsed=answer)

    transport = SimpleNamespace(responses=Transport())
    for module in (matching, vision, text_model):
        monkeypatch.setattr(module, "_client_from_environment", lambda: transport)

    def approve(request: ReviewRequest) -> bool:
        assert bool(request.images) == (request.stage == "visual")
        approvals.append(request.stage)
        return True

    video = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 2, (96, 96))
    pixels = np.random.default_rng(3)
    for _ in range(12):
        writer.write(pixels.integers(0, 255, (96, 96, 3), dtype=np.uint8))
    writer.release()
    with TestClient(create_app(tmp_path), headers={"X-Demo-Passcode": "test"}) as client:
        case_id = client.post(
            "/api/cases",
            json={"order_id": "UJ-48213", "claim_type": "damaged", "description": "Torn item"},
        ).json()["id"]
        worker = CaseJudge(Store(tmp_path))
        prepared = worker.prepare(case_id, video, approve)
        assert prepared.evidence and approvals == ["visual", "visual", "complaint", "reason"]
        assert reasons.ReasonSelection in calls
        # A different byte stream for the same case must not inherit approval.
        changed = tmp_path / "other" / case_id
        changed.mkdir(parents=True)
        (changed / "video.mp4").write_bytes(video.read_bytes() + b"other")
        assert not worker.run(changed).evidence
        before = len(calls)
        url = f"/api/cases/{case_id}"
        assert (
            client.post(
                url + "/video", files={"video": ("clip.mp4", video.read_bytes())}
            ).status_code
            == 202
        )
        assert "event: done" in client.get(url + "/events").text
        case = client.get(f"/api/shop/cases/{case_id}").json()
        assert case["status"] == "ready"
        saved = tmp_path / "cases" / case_id / "verdict.json"
        assert (
            prepared
            == Verdict.model_validate(case["verdict"])
            == Verdict.model_validate_json(saved.read_bytes())
        )
        assert "verdict" not in client.get(url).json()
        for ref in (prepared.evidence[0].frame, prepared.evidence[0].listing_photo):
            response = client.get(f"/api/files/cases/{case_id}/{ref}")
            assert response.status_code == 200 and response.content.startswith(b"\xff\xd8")
        assert client.get(f"/api/files/cases/{case_id}/frames/missing.png").status_code == 404
        with pytest.raises(ValueError, match="before an upload"):
            worker.prepare(case_id, video, approve)
        assert len(calls) == before

        # An upload accepted while the operator reviews takes the local path.
        racing = client.post(
            "/api/cases", json={"order_id": "UJ-48213", "claim_type": "damaged"}
        ).json()["id"]
        approvals.clear()

        def race(request: ReviewRequest) -> bool:
            if not approvals:
                assert (
                    client.post(
                        f"/api/cases/{racing}/video",
                        files={"video": ("clip.mp4", video.read_bytes())},
                    ).status_code
                    == 202
                )
            return approve(request)

        with pytest.raises(ValueError, match="before an upload"):
            worker.prepare(racing, video, race)
        assert not list((tmp_path / ".judge-reviews" / racing).iterdir())


@pytest.mark.parametrize("change", ["second_photo", "order_variant", "product_description"])
def test_review_uses_current_catalog_and_all_photos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "test")
    photos = [
        cv2.imencode("." + ext, np.full((16, 16, 3), value, dtype=np.uint8))[1].tobytes()
        for (ext, _), value in zip(PHOTO_FORMATS.values(), (30, 110, 200), strict=True)
    ]
    model_inputs: list[JudgeInputs] = []

    def capture_inputs(directory: Path, inputs: JudgeInputs, **kwargs: object) -> Verdict:
        model_inputs.append(inputs)
        fixture = Path(judge.__file__).parent / "fixtures/verdict.sample.json"
        return Verdict.model_validate_json(fixture.read_bytes()).model_copy(
            update={"case_id": directory.name}
        )

    # Keep the real adapter, intake and on-disk verdict publication. Capture only
    # the point at which the reviewed pipeline would process the private inputs.
    monkeypatch.setattr(judge, "run_uploaded_case", capture_inputs)
    app = create_app(tmp_path)
    with TestClient(app, headers={"X-Demo-Passcode": "test"}) as client:
        response = client.post(
            "/api/listings",
            data={"title": "Rucksack", "price": "125", "colors": "Emerald", "sizes": "XL"},
            files=[("photos", ("bag.png", photo, "image/png")) for photo in photos],
        )
        assert response.status_code == 201
        product = response.json()
        order = next(
            o for o in client.get("/api/orders").json() if o["listing_id"] == product["id"]
        )
        response = client.post(
            "/api/cases",
            json={"order_id": order["id"], "claim_type": "missing", "description": "Missing strap"},
        )
        assert response.status_code == 201
        case_id = response.json()["id"]
        directory = tmp_path / "cases" / case_id
        directory.mkdir(parents=True, exist_ok=True)
        video = directory / "video.mp4"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 2, (32, 32))
        assert writer.isOpened()
        try:
            for _ in range(12):
                writer.write(np.full((32, 32, 3), 170, dtype=np.uint8))
        finally:
            writer.release()

        worker = app.state.judge
        assert isinstance(worker, CaseJudge)
        assert worker.run(directory).case_id == case_id
        with pytest.raises(ReviewRequired):
            worker.prepare(case_id, video, lambda _: False)
        assert not model_inputs

        reviewed_photos: list[bytes] = []

        def approve(request: ReviewRequest) -> bool:
            assert request.stage == "visual"
            assert [name for name, _ in request.images] == [
                f"listing/{i}.{ext}" for i, (ext, _) in enumerate(PHOTO_FORMATS.values(), 1)
            ]
            reviewed_photos.extend(image for _, image in request.images)
            return True

        prepared = worker.prepare(case_id, video, approve)
        assert reviewed_photos == photos
        (inputs,) = model_inputs
        assert inputs.order.id == order["id"] and inputs.order.listing_id == product["id"]
        assert inputs.order.variant.model_dump() == {"color": "Emerald", "size": "XL"}
        assert inputs.listing.model_dump(mode="json") == product
        assert (inputs.claim_type, inputs.description) == ("missing", "Missing strap")
        assert [int(photo.image[0, 0, 0]) for photo in inputs.listing_photos] == [30, 110, 200]
        assert all(photo.privacy_reviewed for photo in inputs.listing_photos)
        assert worker.run(directory) == prepared

        with Store(tmp_path).transaction() as db:
            if change == "second_photo":
                second = product["photos"][1].removeprefix("/api/files/")
                db.execute("UPDATE listing_photos SET image=? WHERE path=?", (photos[2], second))
            elif change == "order_variant":
                db.execute("UPDATE orders SET size='S' WHERE id=?", (order["id"],))
            else:
                updated = {**product, "description": "Revised model"}
                db.execute(
                    "UPDATE products SET body=? WHERE id=?", (json.dumps(updated), product["id"])
                )
        fallback = worker.run(directory)
        assert fallback.case_id == case_id
        assert [step.name for step in fallback.steps] == ["sampling"]
        assert fallback != prepared and len(model_inputs) == 1

        with Store(tmp_path).transaction() as db:
            path = product["photos"][0].removeprefix("/api/files/")
            db.execute("UPDATE listing_photos SET mime='unknown' WHERE path=?", (path,))
        with pytest.raises(ValueError, match="Unsupported listing photo format"):
            worker.prepare(case_id, video, approve)
