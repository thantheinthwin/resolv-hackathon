"""Model-assisted bilingual reasons can only choose existing grounded facts."""

import json
from types import SimpleNamespace

import pytest

from api.app.contracts import Check, CheckStatus, Finding, Reason, Verdict
from judge.reasons import generate_reason


class FakeResponses:
    def __init__(self, *outputs: object) -> None:
        self.outputs = iter(outputs)
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        out = next(self.outputs)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(output_parsed=out)


def result(*, status: CheckStatus = "flag", translated: bool = True) -> Verdict:
    return Verdict(
        case_id="UJ-PRIVATE-12345",
        verdict="needs_human",
        display="unsure",
        leaning="buyer",
        confidence=0.89,
        flags=[],
        checks={
            "damage": Check(
                status=status,
                confidence=0.9,
                findings=[
                    Finding(
                        t=8.1254,
                        note_en="The case is scratched.",
                        note_th="ตัวเคสมีรอยขีดข่วน" if translated else "",
                    ),
                    Finding(
                        t=9.75,
                        note_en="The screen is cracked.",
                        note_th="หน้าจอแตกร้าว" if translated else "",
                    ),
                ],
            ),
            "count": Check(
                status="flag",
                confidence=1,
                findings=[Finding(t=33, note_en="The cable is absent.", note_th="ไม่พบสาย")],
            ),
        },
        evidence=[],
        reason=Reason(en="Confidence is below 90%.", th="ความมั่นใจต่ำกว่า 90%"),
        steps=[],
    )


def test_reuses_one_exact_finding_in_both_languages_and_keeps_original_reason() -> None:
    verdict = result()
    responses = FakeResponses({"finding_id": 0})
    reason = generate_reason(
        verdict,
        "damage",
        privacy_approved=True,
        client=SimpleNamespace(responses=responses),
        model="test-model",
    )

    assert reason.en.startswith(verdict.reason.en)
    assert reason.th.startswith(verdict.reason.th)
    assert "8.1254" in reason.en and "8.1254" in reason.th
    assert "The case is scratched." in reason.en and "ตัวเคสมีรอยขีดข่วน" in reason.th
    assert "9.75" not in reason.en and "9.75" not in reason.th
    assert Reason.model_validate_json(reason.model_dump_json()) == reason
    assert verdict.reason.en == "Confidence is below 90%."
    assert len(responses.calls) == 1
    call = responses.calls[0]
    assert call["store"] is False
    payload = json.loads(call["input"][1]["content"])
    assert [fact["id"] for fact in payload["untrusted_findings"]] == [0, 1]
    assert "UJ-PRIVATE-12345" not in str(payload)
    assert "8.1254" not in str(payload)
    assert "The cable is absent." not in str(payload)


@pytest.mark.parametrize(
    ("approved", "status", "translated"),
    [(False, "flag", True), (True, "pass", True), (True, "flag", False)],
)
def test_no_call_without_review_or_a_bilingual_finding_for_the_leaning(
    approved: bool, status: CheckStatus, translated: bool
) -> None:
    verdict = result(status=status, translated=translated)
    responses = FakeResponses()
    reason = generate_reason(
        verdict,
        "damage",
        privacy_approved=approved,
        client=SimpleNamespace(responses=responses),
        model="test-model",
    )
    assert reason == verdict.reason
    assert not responses.calls


@pytest.mark.parametrize(
    ("outputs", "calls"),
    [
        (({"finding_id": 1000}, None), 2),
        (({"finding_id": 0, "text": "Invented fact"}, {"finding_id": "0"}), 2),
        ((TimeoutError("private diagnostics"), None), 2),
        (({"finding_id": None},), 1),
    ],
)
def test_bad_selection_or_unavailable_model_preserves_fallback(
    outputs: tuple[object, ...], calls: int
) -> None:
    verdict = result()
    responses = FakeResponses(*outputs)
    reason = generate_reason(
        verdict,
        "damage",
        privacy_approved=True,
        client=SimpleNamespace(responses=responses),
        model="test-model",
    )
    assert reason == verdict.reason
    assert len(responses.calls) == calls
