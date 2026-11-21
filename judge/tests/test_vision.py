"""Tests-first contract for privacy-reviewed, unbiased OpenAI visual observation."""

from collections.abc import Sequence
from types import SimpleNamespace

import numpy as np
import pytest

from judge.privacy import SanitizedFrame
from judge.sampling import SampledFrame
from judge.vision import (
    MAX_OBSERVATION_FRAMES,
    VisionError,
    VisionObservation,
    observe_product,
)


class FakeResponses:
    def __init__(self, results: Sequence[object]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(output_parsed=item)


class FakeClient:
    def __init__(self, *results: object) -> None:
        self.responses = FakeResponses(results)


def frame(timestamp: float) -> SanitizedFrame:
    return SanitizedFrame(
        timestamp_seconds=timestamp,
        image=np.full((48, 48, 3), 127, dtype=np.uint8),
        faces_redacted=1,
        regions_redacted=1,
    )


def finding(timestamp: float) -> dict[str, object]:
    return {
        "t": timestamp,
        "category": "color",
        "value": "navy",
        "confidence": 0.92,
    }


def report(*timestamps: float) -> dict[str, object]:
    return {
        "status": "observed",
        "findings": [finding(t) for t in timestamps],
        "note_en": "The visible product is navy.",
    }


def test_requires_manual_privacy_approval_before_model_call() -> None:
    client = FakeClient(report(1.0))
    with pytest.raises(VisionError, match="privacy approval"):
        observe_product([frame(1.0)], client=client, model="mock")
    assert not client.responses.calls


def test_rejects_unsanitized_sampled_frame() -> None:
    client = FakeClient(report(1.0))
    raw = SampledFrame(
        timestamp_seconds=1.0,
        image=frame(1.0).image,
        blur_score=100.0,
        scene_change=False,
    )
    with pytest.raises(VisionError, match="SanitizedFrame"):
        observe_product([raw], client=client, model="mock", privacy_approved=True)  # type: ignore[list-item]
    assert not client.responses.calls


def test_rejects_empty_and_unsorted_frames() -> None:
    client = FakeClient(report(1.0))
    with pytest.raises(VisionError, match="at least one"):
        observe_product([], client=client, model="mock", privacy_approved=True)
    with pytest.raises(VisionError, match="increasing"):
        observe_product([frame(2.0), frame(1.0)], client=client, model="mock", privacy_approved=True)
    assert not client.responses.calls


def test_strict_structured_request_contains_only_sanitized_images() -> None:
    client = FakeClient(report(1.0))
    result = observe_product([frame(1.0)], client=client, model="mock", privacy_approved=True)
    assert isinstance(result, VisionObservation)
    assert result.status == "observed"
    assert result.findings[0].t == 1.0
    call = client.responses.calls[0]
    assert call["model"] == "mock"
    assert call["text_format"] is VisionObservation
    assert call["timeout"] == 20.0
    assert call["store"] is False
    messages = call["input"]
    assert isinstance(messages, list)
    assert len(messages) == 2
    content = messages[1]["content"]
    images = [part for part in content if part["type"] == "input_image"]
    assert len(images) == 1
    assert images[0]["image_url"].startswith("data:image/jpeg;base64,")
    assert "I ordered black" not in str(messages)
    assert "buyer_name" not in str(messages)
    assert "listing price" not in str(messages)


def test_grounded_timestamp_snaps_to_frame() -> None:
    client = FakeClient(report(1.03))
    result = observe_product([frame(1.0)], client=client, model="mock", privacy_approved=True)
    assert result.status == "observed"
    assert result.findings[0].t == 1.0


def test_drops_hallucinated_timestamps() -> None:
    client = FakeClient(report(1.0, 99.0))
    result = observe_product([frame(1.0)], client=client, model="mock", privacy_approved=True)
    assert [item.t for item in result.findings] == [1.0]


def test_only_ungrounded_findings_become_unclear() -> None:
    client = FakeClient(report(99.0))
    result = observe_product([frame(1.0)], client=client, model="mock", privacy_approved=True)
    assert result.status == "unclear"
    assert result.findings == []


def test_invalid_structured_output_is_retried_once() -> None:
    malformed = {"status": "observed", "findings": [{"category": "illegal"}], "note_en": "bad"}
    client = FakeClient(malformed, report(1.0))
    result = observe_product([frame(1.0)], client=client, model="mock", privacy_approved=True)
    assert result.status == "observed"
    assert len(client.responses.calls) == 2


def test_two_transport_failures_return_unclear_without_exception_details() -> None:
    client = FakeClient(TimeoutError("private endpoint address"), TimeoutError("again"))
    result = observe_product([frame(1.0)], client=client, model="mock", privacy_approved=True)
    assert result.status == "unclear"
    assert "private endpoint" not in result.note_en
    assert len(client.responses.calls) == 2


def test_none_parsed_output_returns_unclear_after_retry() -> None:
    client = FakeClient(None, None)
    result = observe_product([frame(1.0)], client=client, model="mock", privacy_approved=True)
    assert result.status == "unclear"
    assert len(client.responses.calls) == 2


def test_invalid_image_blocks_network() -> None:
    client = FakeClient(report(1.0))
    bad = frame(1.0).model_copy(update={"image": np.zeros((3, 3), dtype=np.uint8)})
    with pytest.raises(VisionError, match="image"):
        observe_product([bad], client=client, model="mock", privacy_approved=True)
    assert not client.responses.calls


def test_frame_limit_keeps_first_and_last_timestamps() -> None:
    frames = [frame(float(t)) for t in range(MAX_OBSERVATION_FRAMES + 3)]
    client = FakeClient({"status": "unclear", "findings": [], "note_en": "Cannot identify."})
    result = observe_product(frames, client=client, model="mock", privacy_approved=True)
    assert result.status == "unclear"
    content = client.responses.calls[0]["input"][1]["content"]
    images = [part for part in content if part["type"] == "input_image"]
    assert len(images) == MAX_OBSERVATION_FRAMES
    text_parts = [part["text"] for part in content if part["type"] == "input_text"]
    assert "t=0.000" in " ".join(text_parts)
    assert f"t={float(len(frames) - 1):.3f}" in " ".join(text_parts)


def test_without_injected_client_require_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(VisionError, match="OPENAI_MODEL"):
        observe_product([frame(1.0)], privacy_approved=True)
