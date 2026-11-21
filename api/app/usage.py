"""Daily case intake limits, charged in the same write transaction as the case."""

import hmac
import ipaddress
import math
import secrets
import sqlite3
from datetime import UTC, datetime, time, timedelta, timezone

from fastapi import HTTPException

COMPETITION_ZONE = timezone(timedelta(hours=7), "Asia/Bangkok")
DAILY_TOTAL_LIMIT = 50
DAILY_IP_LIMIT = 10


def _quota_day(when: datetime) -> str:
    # The API created timestamps in UTC before counters were introduced.
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(COMPETITION_ZONE).date().isoformat()


def initialize_usage(db: sqlite3.Connection) -> None:
    """Backfill surviving cases created today on upgrade. Legacy IPs were never recorded."""
    day = _quota_day(datetime.now(UTC))
    db.execute("DELETE FROM usage WHERE day < ?", (day,))
    if db.execute("SELECT 1 FROM usage WHERE day = ?", (day,)).fetchone():
        return
    timestamps = db.execute("SELECT created_at FROM cases WHERE id != 'UJ-SAMPLE'")
    total = sum(_quota_day(datetime.fromisoformat(stamp)) == day for (stamp,) in timestamps)
    db.execute(
        "INSERT INTO usage (day, total, salt) VALUES (?, ?, ?)",
        (day, total, secrets.token_bytes(32)),
    )


def _peer_bytes(host: str | None) -> bytes:
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        # A missing/non-IP ASGI peer shares one bucket (e.g. in-process transports).
        return b"unknown"
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.packed


def consume_case_quota(db: sqlite3.Connection, host: str | None, when: datetime) -> None:
    """Called under Store.transaction's BEGIN IMMEDIATE before inserting a new case."""
    day = _quota_day(when)
    row = db.execute("SELECT total, salt FROM usage WHERE day = ?", (day,)).fetchone()
    if row is None:
        db.execute("DELETE FROM usage WHERE day < ?", (day,))
        total, salt = 0, secrets.token_bytes(32)
        db.execute("INSERT INTO usage (day, total, salt) VALUES (?, ?, ?)", (day, total, salt))
    else:
        total, salt = row
    digest = hmac.digest(salt, _peer_bytes(host), "sha256")
    row = db.execute(
        "SELECT total FROM daily_ip_usage WHERE day = ? AND peer_digest = ?", (day, digest)
    ).fetchone()
    peer_total = row[0] if row else 0
    if total >= DAILY_TOTAL_LIMIT or peer_total >= DAILY_IP_LIMIT:
        local = when.astimezone(COMPETITION_ZONE)
        reset = datetime.combine(local.date() + timedelta(days=1), time.min, COMPETITION_ZONE)
        limit = "Demo" if total >= DAILY_TOTAL_LIMIT else "IP address"
        raise HTTPException(
            429,
            f"{limit} daily case limit reached.",
            headers={"Retry-After": str(math.ceil((reset - local).total_seconds()))},
        )
    db.execute("UPDATE usage SET total = total + 1 WHERE day = ?", (day,))
    db.execute(
        "INSERT INTO daily_ip_usage (day, peer_digest, total) VALUES (?, ?, 1) "
        "ON CONFLICT(day, peer_digest) DO UPDATE SET total = total + 1",
        (day, digest),
    )
