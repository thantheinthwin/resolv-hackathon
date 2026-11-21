"""Exact-content approvals cannot be reused for a replacement upload."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app.contracts import Case
from api.app.reviews import (
    clear_reviews,
    initialize_reviews,
    require_approval,
    reset_reviews,
    review_router,
)
from api.app.store import Store, get_case, save_case
from judge import ReviewRequest, ReviewRequired


@pytest.fixture
def review_api(tmp_path: Path) -> tuple[TestClient, Store]:
    store = Store(tmp_path)
    store.initialize()
    with store.transaction() as db:
        initialize_reviews(db)
        case = Case(
            id="first",
            order_id="order",
            claim_type="damaged",
            description="",
            status="checking",
            created_at=datetime.now(UTC),
        )
        save_case(db, case)
    app = FastAPI()
    app.state.runner = Mock(store=store)
    app.include_router(review_router)
    return TestClient(app), store


url = "/shop/cases/first/review"


def identity(client: TestClient) -> dict[str, str]:
    response = client.get(url)
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    return {k: response.json()[k] for k in ("upload_id", "stage", "fingerprint")}


def test_previews_exact_decisions_and_replacements(review_api: tuple[TestClient, Store]) -> None:
    client, store = review_api
    first = ReviewRequest("visual", "Review this photograph.", (("listing/1.jpg", b"image"),))
    with pytest.raises(ReviewRequired):
        require_approval(store, "first", first)
    original = identity(client)
    preview = client.get(url).json()
    assert preview["images"] == [{"name": "listing/1.jpg", "jpeg_base64": "aW1hZ2U="}]
    assert preview["text"] == first.text
    changed = ReviewRequest("visual", first.text, (("listing/1.jpg", b"changed"),))
    with pytest.raises(ReviewRequired):
        require_approval(store, "first", changed)
    assert client.post(url + "/approve", json=original).status_code == 409
    current = identity(client)

    def approve(_: int) -> int:
        return client.post(url + "/approve", json=current).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve, (1, 2))) == [204, 409]
    assert client.get(url).status_code == 404
    assert require_approval(Store(store.root), "first", changed)
    with store.transaction() as db:
        reset_reviews(db, "first")
    with pytest.raises(ReviewRequired):
        require_approval(store, "first", changed)
    replacement = identity(client)
    assert replacement["fingerprint"] == current["fingerprint"]
    assert replacement["upload_id"] != current["upload_id"]
    assert client.post(url + "/approve", json=current).status_code == 409
    assert client.post(url + "/decline", json=replacement).status_code == 204
    assert client.get(url).status_code == 404
    with store.connection() as db:
        case = get_case(db, "first")
        assert case.status == "failed" and case.progress[-1].event == "done"
        for table in ("pending_reviews", "review_approvals", "review_uploads"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)


def test_case_delete_purges_private_content(review_api: tuple[TestClient, Store]) -> None:
    client, store = review_api
    with pytest.raises(ReviewRequired):
        require_approval(store, "first", ReviewRequest("complaint", "Private description"))
    pending = identity(client)
    with store.transaction() as db:
        clear_reviews(db, "first")
        db.execute("DELETE FROM cases WHERE id='first'")
    assert client.get(url).status_code == 404
    assert client.post(url + "/approve", json=pending).status_code == 404
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM pending_reviews").fetchone() == (0,)


def test_operator_cli_only_submits_the_inspected_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from api import review_pending

    monkeypatch.setenv("DEMO_PASSCODE", "buyer")
    monkeypatch.setenv("SHOP_PASSCODE", "shop")
    req = ReviewRequest("reason", "Review the exact text.")
    upload_id = "a" * 32
    identity = {"stage": req.stage, "upload_id": upload_id, "fingerprint": req.fingerprint}
    pending = review_pending.PendingReview(**identity, text=req.text, images=[])
    fetch = Mock(status=200)
    fetch.read.return_value = pending.model_dump_json()
    preview_connection = Mock()
    preview_connection.getresponse.return_value = fetch
    decision_connection = Mock()
    decision_connection.getresponse.return_value = Mock(status=204)
    connect = Mock(side_effect=[preview_connection, decision_connection, preview_connection])
    monkeypatch.setattr(review_pending, "HTTPConnection", connect)

    def inspect(_: ReviewRequest) -> str:
        preview_connection.close.assert_called_once()
        preview_connection.request.side_effect = ConnectionResetError("expired connection")
        return "approve"

    choose = Mock(side_effect=inspect)
    monkeypatch.setattr(review_pending, "review_choice", choose)
    review_pending.review_pending("first", 8000)
    choose.assert_called_once_with(req)
    assert connect.call_count == 2
    decision_connection.close.assert_called_once()
    posted = decision_connection.request.call_args
    assert posted.args == ("POST", "/api/shop/cases/first/review/approve")
    assert (
        review_pending.ReviewIdentity.model_validate_json(posted.kwargs["body"]).model_dump()
        == identity
    )
    assert posted.kwargs["headers"]["X-Shop-Passcode"] == "shop"
    assert posted.kwargs["headers"]["X-Demo-Passcode"] == "buyer"

    fetch.read.return_value = pending.model_copy(update={"text": "changed"}).model_dump_json()
    preview_connection.request.side_effect = None
    with pytest.raises(SystemExit, match="fingerprint"):
        review_pending.review_pending("first", 8000)
    choose.assert_called_once()
    captured = capsys.readouterr()
    assert "buyer" not in captured.out + captured.err
    assert "shop" not in captured.out + captured.err


@pytest.mark.parametrize("approve_first", [False, True])
def test_buyer_deletion_and_review_approval_are_serialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approve_first: bool
) -> None:
    from threading import Event

    from api.app.contracts import Verdict
    from api.app.fake import FakeJudge
    from api.main import create_app

    store = Store(tmp_path)
    pending, running, release = Event(), Event(), Event()

    class ReviewingJudge(FakeJudge):
        def run(self, folder: Path) -> Verdict:
            try:
                require_approval(store, folder.name, ReviewRequest("visual", "Private preview"))
            except ReviewRequired:
                pending.set()
                raise
            running.set()
            assert release.wait(10)
            return super().run(folder)

    monkeypatch.setenv("DEMO_PASSCODE", "buyer")
    monkeypatch.setenv("SHOP_PASSCODE", "shop")
    app = create_app(tmp_path, ReviewingJudge())
    shop = {"X-Shop-Passcode": "shop"}
    with TestClient(app, headers={"X-Demo-Passcode": "buyer"}) as client:
        created = client.post("/api/cases", json={"order_id": "UJ-48213", "claim_type": "damaged"})
        assert created.status_code == 201
        case_id = created.json()["id"]
        upload = tmp_path / "staged"
        upload.write_bytes(b"accepted video")
        app.state.runner.submit(case_id, upload)
        assert pending.wait(10)
        case_url = f"/api/cases/{case_id}"
        review_url = f"/api/shop/cases/{case_id}/review"
        preview = client.get(review_url, headers=shop).json()
        decision = {name: preview[name] for name in ("upload_id", "stage", "fingerprint")}
        if approve_first:
            try:
                assert (
                    client.post(review_url + "/approve", headers=shop, json=decision).status_code
                    == 204
                )
                assert running.wait(10)
                assert client.delete(case_url).status_code == 409
            finally:
                release.set()
            assert "event: done" in client.get(case_url + "/events").text

        assert client.delete(case_url).status_code == 204
        assert not (tmp_path / "cases" / case_id).exists()
        assert client.get(review_url, headers=shop).status_code == 404
        for action in ("approve", "decline"):
            assert (
                client.post(review_url + "/" + action, headers=shop, json=decision).status_code
                == 404
            )


def test_existing_store_protects_review_data_on_upgrade(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.initialize()
    database = tmp_path / "cases.sqlite3"
    database.chmod(0o644)
    (tmp_path / "cases").chmod(0o755)
    store.initialize()
    assert database.stat().st_mode & 0o077 == 0
    for name in ("cases", ".judge-reviews", ".incoming", ".replaced"):
        assert (tmp_path / name).stat().st_mode & 0o077 == 0
