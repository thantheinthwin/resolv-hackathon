from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app.contracts import Case, CaseStatus, Decision, Verdict
from api.app.fake import SAMPLE_VERDICT
from api.app.sample import ORDER
from api.app.store import Store, save_case
from api.main import create_app

# One competition day's cap. The sample case is removed before loading these.
DAILY_CASES = 50
STATES: tuple[CaseStatus, ...] = (
    "awaiting_video",
    "ready",
    "checking",
    "decided",
    "failed",
    "ready",
)
BUYER_STATES = ("sent", "with_shop", "checking", "replied", "failed", "with_shop")


def seed_case_list(store: Store) -> None:
    sample = Verdict.model_validate_json(SAMPLE_VERDICT.read_bytes())
    with store.transaction() as db:
        # Insert even-numbered cases before odd ones so row order cannot stand in for time.
        for index in [*range(0, DAILY_CASES, 2), *range(1, DAILY_CASES, 2)]:
            variant = index % len(STATES)
            case_id = f"UJ-LIST-{index:02d}"
            verdict = None
            decision = None
            if STATES[variant] in ("ready", "decided"):
                verdict = sample.model_copy(update={"case_id": case_id})
                if variant != 1:
                    verdict = verdict.model_copy(
                        update={
                            "verdict": "seller_right",
                            "leaning": "seller",
                            "display": "clear",
                            "confidence": 0.96,
                        }
                    )
            if STATES[variant] == "decided":
                decision = Decision(
                    choice="disagree", reason="video unclear", note_for_buyer="Reviewed."
                )
            save_case(
                db,
                Case(
                    id=case_id,
                    order_id=ORDER.id,
                    claim_type="damaged",
                    description="Packaging dented",
                    created_at=datetime(2026, 11, 21, tzinfo=UTC) + timedelta(minutes=index),
                    status=STATES[variant],
                    verdict=verdict,
                    decision=decision,
                ),
            )


def test_case_lists_from_file_backed_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "list-test")
    with TestClient(create_app(tmp_path), headers={"X-Demo-Passcode": "list-test"}) as client:
        assert client.delete("/api/cases/UJ-SAMPLE").status_code == 204
        seed_case_list(Store(tmp_path))
        newest = list(reversed(range(DAILY_CASES)))
        shop = client.get("/api/shop/cases")
        assert shop.status_code == 200
        unsure = [i for i in newest if i % len(STATES) == 1]
        remaining = [i for i in newest if i % len(STATES) != 1]
        assert [row["id"] for row in shop.json()] == [
            f"UJ-LIST-{i:02d}" for i in unsure + remaining
        ]
        reports = client.get("/api/my/cases")
        assert reports.status_code == 200
        # Exact equality catches any extra fields, including nested shop verdicts or decisions.
        assert reports.json() == [
            {
                "id": f"UJ-LIST-{i:02d}",
                "status": BUYER_STATES[i % len(STATES)],
                "note_for_buyer": "Reviewed." if i % len(STATES) == 3 else None,
            }
            for i in newest
        ]
