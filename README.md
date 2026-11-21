# resolv-hackathon

Hackathon workspace for reviewing buyer complaints against video evidence, order details, and product listings.

Start with the [agent guide](AGENTS.md) for team rules, service ownership, and contract checks.

| Directory | Purpose |
| --- | --- |
| `web/` | Buyer and shop-owner interface |
| `api/` | FastAPI service for case intake and review |
| `judge/` | Python package for evidence analysis |

## Run the competition baseline

Install Python 3.12, Node.js 22.12 or later, npm, and FFmpeg with ffprobe. From the
repository root, run `make setup`. Set `DEMO_PASSCODE` in your shell, then run
`make dev` to start the web app on port 3000 and the API on port 8000.
The web server uses the passcode to fetch the seeded order. Use the same value
in the `X-Demo-Passcode` header when exercising `/api` routes directly.

Open `http://localhost:3000` and choose **View your orders**. The seeded shop
case is available through `/api/shop/cases/UJ-SAMPLE`. It contains a sample
verdict for testing the integration. Video submission and live job progress
are scheduled for the next checkpoint.

Run `make check` for the Python and web checks. After changing an API route,
run `npm --prefix web run gen:api` against the running API and check the
generated TypeScript diff.

## Team activity

Team members and agents can claim paths and watch active work across devices. [Plugin installation and team coordinator setup](plugins/team-activity/README.md)
