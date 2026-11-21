"""Persistent demo products and their delivered orders."""

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException

from api.app.contracts import Listing, Order, Variant
from api.app.sample import LISTING, ORDER, OrderWithListing


def insert_product(db: sqlite3.Connection, listing: Listing) -> None:
    db.execute(
        "INSERT INTO products(id, body) VALUES (?, ?)", (listing.id, listing.model_dump_json())
    )


def insert_order(db: sqlite3.Connection, order: Order) -> None:
    db.execute(
        "INSERT INTO orders(id, product_id, color, size, quantity, delivered_at, buyer_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            order.id,
            order.listing_id,
            order.variant.color,
            order.variant.size,
            order.quantity,
            order.delivered_at.isoformat(),
            order.buyer_name,
        ),
    )


def create_reportable_product(db: sqlite3.Connection, listing: Listing) -> None:
    """Every new demo product is delivered to the buyer once."""
    insert_product(db, listing)
    insert_order(
        db,
        Order(
            id=f"UJ-{uuid4().hex}",
            listing_id=listing.id,
            variant=Variant(
                color=next(iter(listing.colors), ""), size=next(iter(listing.sizes), "")
            ),
            quantity=1,
            delivered_at=datetime.now(UTC),
            buyer_name=ORDER.buyer_name,
        ),
    )


def initialize_catalog(db: sqlite3.Connection) -> None:
    """Run under the startup write transaction; preserve original IDs and photo paths."""
    if db.execute("SELECT 1 FROM products WHERE id=?", (LISTING.id,)).fetchone() is None:
        insert_product(db, LISTING)
    if db.execute("SELECT 1 FROM orders WHERE id=?", (ORDER.id,)).fetchone() is None:
        insert_order(db, ORDER)


def delivered_orders(db: sqlite3.Connection) -> list[OrderWithListing]:
    return [
        OrderWithListing(
            id=order_id,
            listing_id=listing_id,
            variant=Variant(color=color, size=size),
            quantity=quantity,
            delivered_at=delivered_at,
            buyer_name=buyer_name,
            listing=Listing.model_validate_json(body),
        )
        for order_id, listing_id, color, size, quantity, delivered_at, buyer_name, body in db.execute(
            """SELECT o.id, o.product_id, o.color, o.size, o.quantity, o.delivered_at,
                       o.buyer_name, p.body
                FROM orders AS o JOIN products AS p ON p.id=o.product_id ORDER BY (o.id = ?) DESC, o.rowid""",
            (ORDER.id,),
        )
    ]


def require_order(db: sqlite3.Connection, order_id: str) -> None:
    if db.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone() is None:
        raise HTTPException(404, "Order not found.")
