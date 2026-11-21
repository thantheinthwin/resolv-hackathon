"""Command-line client bundled with the Team Activity skill."""

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def request(method: str, path: str, payload: dict | None = None, session: str | None = None) -> str:
    url = os.environ["TEAM_ACTIVITY_URL"].rstrip("/")
    address = urlsplit(url)
    if address.scheme != "https" and not (
        address.scheme == "http" and address.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        raise ValueError("Use HTTPS or a localhost tunnel for the team connection")
    headers = {"Authorization": "Bearer " + os.environ["TEAM_ACTIVITY_TOKEN"]}
    if session:
        headers["X-Activity-Session"] = session
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url + path, method=method, data=data, headers=headers)

    # A misrouted endpoint must not forward either credential to a redirect target.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: object) -> None:
            return None

    with urllib.request.build_opener(NoRedirect).open(req, timeout=8) as response:
        return response.read().decode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "watch", "heartbeat", "release", "init"):
        sub.add_parser(name)
    claim = sub.add_parser("claim")
    for name in ("member", "agent", "task", "branch"):
        claim.add_argument("--" + name, required=True)
    claim.add_argument("paths", nargs="+")
    args = parser.parse_args()
    if args.command in ("list", "watch"):
        previous = None
        while True:
            snapshot = request("GET", "/activity")
            if snapshot != previous:
                print(json.dumps(json.loads(snapshot), ensure_ascii=False, indent=2), flush=True)
                previous = snapshot
            if args.command == "list":
                return
            time.sleep(2)

    # Caller supplies a unique local file for this task; its contents stay out of shared listings.
    session_file = Path(os.environ["TEAM_ACTIVITY_SESSION_FILE"])
    if args.command == "init":
        with os.fdopen(
            os.open(session_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as out:
            out.write(secrets.token_hex(32))
        return
    session = session_file.read_text().strip()
    if len(session) != 64:
        raise ValueError("Invalid session file")
    if args.command == "claim":
        result = request(
            "PUT", "/claim", {k: v for k, v in vars(args).items() if k != "command"}, session
        )
    elif args.command == "heartbeat":
        result = request("POST", "/heartbeat", session=session)
    else:
        result = request("DELETE", "/claim", session=session)
    if result:
        print(result)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        sys.exit(f"Coordinator returned {error.code}: {error.read().decode(errors='replace')}")
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"Team activity unavailable: {error}")
    except KeyboardInterrupt:
        pass
