import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app.contracts import Case
from api.app.sample import LISTING, ORDER
from api.app.store import Store
from api.main import create_app


def test_new_product_is_reportable_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "test")
    headers = {"X-Demo-Passcode": "test"}
    photo = (Path(__file__).parents[1] / "fixtures/tee.png").read_bytes()
    with TestClient(create_app(tmp_path), headers=headers) as client:
        result = client.post(
            "/api/listings",
            data={
                "title": "Blue travel bag",
                "price": 125,
                "colors": ["Blue", "Red"],
                "sizes": ["S", "M"],
            },
            files={"photos": ("bag.png", photo, "image/png")},
        )
        assert result.status_code == 201
        product = result.json()
        orders = client.get("/api/orders").json()
        assert orders[0] == ORDER.model_dump(mode="json")
        assert len(orders) == 2
        order = orders[1]
        assert order["listing"] == product and order["listing_id"] == product["id"]
        assert order["variant"] == {"color": "Blue", "size": "S"} and order["quantity"] == 1
        assert client.get(product["photos"][0]).content == photo
        result = client.post("/api/cases", json={"order_id": order["id"], "claim_type": "damaged"})
        assert result.status_code == 201
        case_id = result.json()["id"]
        assert (
            client.post(
                "/api/cases", json={"order_id": product["id"], "claim_type": "damaged"}
            ).status_code
            == 404
        )

    with TestClient(create_app(tmp_path), headers=headers) as client:
        assert client.get("/api/orders").json() == orders
        inbox = {row["id"]: row for row in client.get("/api/shop/cases").json()}
        assert inbox["UJ-SAMPLE"]["product"] == LISTING.title
        assert inbox[case_id]["product"] == "Blue travel bag"
        assert inbox[case_id]["order_id"] == order["id"]
        assert client.get(f"/api/cases/{case_id}").json() == {
            "id": case_id,
            "status": "sent",
            "note_for_buyer": None,
        }


def test_migrate_pr17_catalog_with_photos_and_existing_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    photo = (Path(__file__).parents[1] / "fixtures/tee.png").read_bytes()
    path = "listings/LS-old/1.png"
    product = LISTING.model_copy(
        update={"id": "LS-old", "photos": [f"/api/files/{path}"], "colors": [], "sizes": []}
    )
    case = Case(
        id="UJ-existing",
        order_id=ORDER.id,
        claim_type="missing",
        status="awaiting_video",
        created_at=datetime.now(UTC),
        description="Missing tee.",
    )
    db = sqlite3.connect(tmp_path / "cases.sqlite3")
    try:
        with db:
            db.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute("INSERT INTO cases VALUES (?, ?)", (case.id, case.model_dump_json()))
            db.execute("CREATE TABLE listings (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute(
                "INSERT INTO listings VALUES (?, ?)", (product.id, product.model_dump_json())
            )
            db.execute(
                "CREATE TABLE listing_photos (path TEXT PRIMARY KEY, mime TEXT NOT NULL, image BLOB NOT NULL)"
            )
            db.execute("INSERT INTO listing_photos VALUES (?, ?, ?)", (path, "image/png", photo))
    finally:
        db.close()

    monkeypatch.setenv("DEMO_PASSCODE", "test")
    headers = {"X-Demo-Passcode": "test"}
    with TestClient(create_app(tmp_path), headers=headers) as client:
        orders = client.get("/api/orders").json()
        assert len(orders) == 2 and orders[0]["id"] == ORDER.id
        assert orders[1]["listing"] == product.model_dump(mode="json")
        assert orders[1]["variant"] == {"color": "", "size": ""}
        assert client.get(product.photos[0]).content == photo
        assert client.get(f"/api/shop/cases/{case.id}").json() == {
            **case.model_dump(mode="json"),
            "photo_findings": [],
        }
        assert (
            client.post(
                "/api/cases", json={"order_id": orders[1]["id"], "claim_type": "wrong_item"}
            ).status_code
            == 201
        )
    with TestClient(create_app(tmp_path), headers=headers) as client:
        assert client.get("/api/orders").json() == orders
        assert client.get("/api/listings").json() == [
            LISTING.model_dump(mode="json"),
            product.model_dump(mode="json"),
        ]
    with Store(tmp_path).connection() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='listings'").fetchone() is None
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_order_failure_rolls_back_product_and_photos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "test")
    with TestClient(create_app(tmp_path), headers={"X-Demo-Passcode": "test"}) as client:
        with Store(tmp_path).transaction() as db:
            db.execute(
                "CREATE TRIGGER reject_order BEFORE INSERT ON orders BEGIN SELECT RAISE(ABORT, 'order failed'); END"
            )
        with pytest.raises(sqlite3.IntegrityError, match="order failed"):
            client.post(
                "/api/listings",
                data={"title": "Will roll back", "price": 0},
                files={
                    "photos": (
                        "photo.png",
                        (Path(__file__).parents[1] / "fixtures/tee.png").read_bytes(),
                    )
                },
            )
        assert client.get("/api/orders").json() == [ORDER.model_dump(mode="json")]
        assert client.get("/api/listings").json() == [LISTING.model_dump(mode="json")]
        with Store(tmp_path).connection() as db:
            assert db.execute("SELECT COUNT(*) FROM listing_photos").fetchone() == (0,)
