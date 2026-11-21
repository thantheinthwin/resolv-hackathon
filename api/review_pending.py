"""Inspect one pending API review on the host. Run again for the next stage."""

import argparse
import base64
import os
from contextlib import closing
from http.client import HTTPConnection
from urllib.parse import quote

from api.app.review_prompt import review_choice
from api.app.reviews import PendingReview, ReviewIdentity
from judge import ReviewRequest


def review_pending(case_id: str, port: int) -> None:
    demo = os.environ.get("DEMO_PASSCODE")
    shop = os.environ.get("SHOP_PASSCODE")
    if not demo or not shop:
        raise SystemExit("Set DEMO_PASSCODE and SHOP_PASSCODE in the host environment.")
    headers = {"X-Demo-Passcode": demo, "X-Shop-Passcode": shop, "Content-Type": "application/json"}
    path = f"/api/shop/cases/{quote(case_id, safe='')}/review"
    with closing(HTTPConnection("127.0.0.1", port, timeout=20)) as connection:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise SystemExit(f"Could not fetch a pending review (HTTP {response.status}).")
        pending = PendingReview.model_validate_json(response.read())
    request = ReviewRequest(
        stage=pending.stage,
        text=pending.text,
        images=tuple(
            (i.name, base64.b64decode(i.jpeg_base64, validate=True)) for i in pending.images
        ),
    )
    if request.fingerprint != pending.fingerprint:
        raise SystemExit("The review fingerprint differs from the displayed content.")
    choice = review_choice(request)
    if choice is None:
        print("The review is still pending.")
        return
    identity = ReviewIdentity(
        stage=pending.stage, upload_id=pending.upload_id, fingerprint=pending.fingerprint
    )
    with closing(HTTPConnection("127.0.0.1", port, timeout=20)) as connection:
        connection.request(
            "POST", f"{path}/{choice}", body=identity.model_dump_json(), headers=headers
        )
        response = connection.getresponse()
        if response.status != 204:
            raise SystemExit(f"Could not record the decision (HTTP {response.status}).")
    print("Approval saved. The job will resume." if choice == "approve" else "Review declined.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    review_pending(args.case_id, args.port)


if __name__ == "__main__":
    main()
