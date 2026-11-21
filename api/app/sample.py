"""Synthetic catalog for the first-hour demo."""

from datetime import UTC, datetime

from api.app.contracts import Listing, Order, Variant


class OrderWithListing(Order):
    listing: Listing


LISTING = Listing(
    id="LS-101",
    title="Everyday cotton tee",
    description="Crew-neck cotton tee.",
    box_contents=["Cotton tee"],
    price=390,
    colors=["Midnight Black", "Navy"],
    sizes=["M", "L"],
    photos=["/api/files/listings/sample/tee.png"],
)
ORDER = OrderWithListing(
    id="UJ-48213",
    listing_id=LISTING.id,
    variant=Variant(color="Midnight Black", size="M"),
    quantity=1,
    delivered_at=datetime(2026, 11, 20, tzinfo=UTC),
    buyer_name="Demo buyer",
    listing=LISTING,
)
