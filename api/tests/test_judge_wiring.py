from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app.contracts import Verdict
from api.app.judging import CaseJudge
from api.app.store import Store
from api.main import create_app
from judge import complaint, matching, reasons, vision


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
                assert approvals == ["visual"]
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
                assert approvals == ["visual", "text"]
                answer = {"confidence": 0.9, "allegations": []}
            else:
                assert schema is reasons.ReasonSelection
                assert approvals == ["visual", "text"]
                answer = {"finding_id": 0}
            return SimpleNamespace(output_parsed=answer)

    transport = SimpleNamespace(responses=Transport())
    for module in (matching, vision, complaint, reasons):
        monkeypatch.setattr(module, "_client_from_environment", lambda: transport)

    def approve(stage: str, files: dict[str, bytes]) -> bool:
        assert ("complaint.txt" in files) == (stage == "text")
        assert ("frames/0.png" in files) == (stage == "visual")
        approvals.append(stage)
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
        assert prepared.evidence and approvals == ["visual", "text"]
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
            assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
        assert client.get(f"/api/files/cases/{case_id}/frames/missing.png").status_code == 404
        assert len(calls) == before
