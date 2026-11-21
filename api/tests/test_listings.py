import asyncio
from collections.abc import AsyncIterator, Iterator
from io import BytesIO
from pathlib import Path
from sqlite3 import IntegrityError

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from api.app import listings
from api.app.store import Store
from api.main import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DEMO_PASSCODE", "catalog-test")
    with TestClient(create_app(tmp_path), headers={"X-Demo-Passcode": "catalog-test"}) as session:
        yield session


def photo(fmt: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (6, 5), (24, 174, 64)).save(buffer, fmt)
    return buffer.getvalue()


def test_shop_form_round_trip_and_restart(client: TestClient, tmp_path: Path) -> None:
    originals = [photo(fmt) for fmt in ("WEBP", "JPEG", "PNG")]
    response = client.post(
        "/api/listings",
        data={
            "title": " Canvas tote ",
            "description": "Cotton",
            "price": "129.50",
            "colors": ["Blue", "Red"],
            "box_contents": ["Bag", "Strap"],
        },
        # Form filenames and reported types do not decide file paths or response types.
        files=[("photos", ("shop.jpeg", image, "application/octet-stream")) for image in originals],
    )
    assert response.status_code == 201
    listing = response.json()
    assert listing["title"] == "Canvas tote"
    assert listing["price"] == 129.5
    assert listing["colors"] == ["Blue", "Red"]
    assert listing["box_contents"] == ["Bag", "Strap"]
    assert listing["sizes"] == []
    assert len(set(listing["photos"])) == 3
    # Reopen the same database through a fresh Store connection and a new app below.
    assert listings.catalog(Store(tmp_path))[-1].id == listing["id"]
    for url, image, mime in zip(
        listing["photos"], originals, ("image/webp", "image/jpeg", "image/png"), strict=True
    ):
        result = client.get(url)
        assert result.status_code == 200
        assert result.headers["content-type"] == mime
        assert result.content == image
        assert client.get(url, headers={"X-Demo-Passcode": "incorrect"}).status_code == 403
    assert client.get(listing["photos"][0] + ".unknown").status_code == 404


def test_listing_survives_api_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_PASSCODE", "catalog-test")
    headers = {"X-Demo-Passcode": "catalog-test"}
    image = photo("JPEG")
    with TestClient(create_app(tmp_path), headers=headers) as session:
        response = session.post(
            "/api/listings", data={"title": "Tee", "price": 0}, files={"photos": ("tee.jpg", image)}
        )
        assert response.status_code == 201
        listing = response.json()
    with TestClient(create_app(tmp_path), headers=headers) as session:
        assert session.get("/api/listings").json() == [
            session.get("/api/orders").json()[0]["listing"],
            listing,
        ]
        assert session.get(listing["photos"][0]).content == image


@pytest.mark.parametrize(
    "fields", [{"title": "   "}, {"price": "-1"}, {"price": "nan"}, {"description": "x" * 1501}]
)
def test_invalid_listing_fields(client: TestClient, fields: dict[str, str]) -> None:
    response = client.post(
        "/api/listings",
        data={"title": "Tee", "price": "25", **fields},
        files={"photos": ("t.png", photo("PNG"))},
    )
    assert response.status_code == 422
    assert len(client.get("/api/listings").json()) == 1


def test_photo_limits_and_rollback(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = photo("PNG")
    fields = {"title": "Tee", "price": "25"}

    def submit(images: list[bytes]) -> Response:
        return client.post(
            "/api/listings", data=fields, files=[("photos", ("p.png", value)) for value in images]
        )

    assert submit([image] * 4).status_code == 422
    assert submit([image, b"invalid"]).status_code == 422
    assert (
        client.post(
            "/api/listings", data=fields, files={"another_field": ("p.png", image)}
        ).status_code
        == 422
    )
    with monkeypatch.context() as patch:
        patch.setattr(listings, "MAX_PHOTO_BYTES", len(image) - 1)
        assert submit([image]).status_code == 422
    with monkeypatch.context() as patch:
        patch.setattr(listings, "MAX_PHOTO_PIXELS", 29)
        assert submit([image]).status_code == 422
    store = Store(tmp_path)
    with store.transaction() as db:
        db.execute(
            "CREATE TRIGGER reject_photo BEFORE INSERT ON listing_photos BEGIN SELECT RAISE(ABORT, 'write failed'); END"
        )
    with pytest.raises(IntegrityError, match="write failed"):
        submit([image])
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM listing_photos").fetchone() == (0,)
    assert len(client.get("/api/listings").json()) == 1


def test_chunked_listing_request_bound(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(listings, "MAX_FORM_BYTES", 120)

    async def stream() -> AsyncIterator[bytes]:
        yield b'--x\r\nContent-Disposition: form-data; name="photos"; filename="photo.png"\r\n\r\n'
        yield b"x" * 121
        raise AssertionError("Server must stop reading once the upload limit is reached")

    async def post_stream() -> Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://test"
        ) as session:
            return await session.post(
                "/api/listings",
                headers={
                    "Content-Type": "multipart/form-data; boundary=x",
                    "X-Demo-Passcode": "catalog-test",
                },
                content=stream(),
            )

    assert asyncio.run(post_stream()).status_code == 422


def test_malformed_multipart_is_a_client_error(client: TestClient) -> None:
    case_id = client.post(
        "/api/cases", json={"order_id": "UJ-48213", "claim_type": "damaged"}
    ).json()["id"]
    for url in ("/api/listings", f"/api/cases/{case_id}/video"):
        response = client.post(
            url, content=b"invalid", headers={"Content-Type": "multipart/form-data; boundary=x"}
        )
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)
