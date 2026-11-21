# Unboxing Judge web desk

Run `make setup` at the repository root. For the integrated API, set the same
server-only `DEMO_PASSCODE` for Next and FastAPI, then run `make dev`.
`API_BASE_URL` overrides the default FastAPI origin on port 8000.
`npm run gen:api` regenerates the shared TypeScript types from OpenAPI.

For a sample walkthrough, use Node 22.13 or later, leave the API origin and
passcode unset, and run `npm run dev` here. The desk stores sample cases under
`data/web-sample`. It calls the repository's Python 3.12 environment with
FFmpeg, ffprobe and the OpenCV dependency installed by the shared setup.
The sample judge returns an unassessed verdict.

For phone upload, open the desk on the laptop's LAN address and connect the
phone to the same network. NEXT_PUBLIC_WEB_ORIGIN can specify a different
phone-accessible web origin at build time.

## Decision and verification record

The web client uses the generated API contracts for both roles. Buyer reports
contain a status and a shop note. Shop case details include the evidence and
decision. The separate sample store supports upload rehearsal while the live
API returns 501 for video intake, phone upload links, and product creation.
The sample adapter calls the team's intake implementation so phone and desktop
uploads share decoding and recording-quality checks.

Case deletion invalidates upload tokens and removes the video and judge
output. Conditional SQLite writes protect a saved decision from a second
reviewer and prevent a late judge result from restoring a deleted case.
The inbox replays stored job events, including the terminal event on reconnect.

### Reproduce the checks

Run `make check` from the root and `npm run build` here. For the regression
suite, use Chrome and install the recording helper with `npx playwright install ffmpeg`.
Set SAMPLE_DATA_DIR and REHEARSAL_DIR to separate paths in a fresh temporary
directory, start the sample server with SAMPLE_DATA_DIR set, and set
REHEARSAL_URL to its localhost URL. Run these commands in order:

1. `node scripts/rehearse.mjs` generates a synthetic clip, records the buyer
   upload and shop decision, and checks buyer response privacy.
2. `node scripts/check-handoffs.mjs` checks the phone flow in emulation, token
   replay, evidence seeking with a fixture, and product creation.
3. `node scripts/review-regressions.mjs` checks deletion, intake boundaries
   and darkness warnings, concurrent decisions, shop product context, job
   events, and the accessible upload percentage in an isolated case store.

The live proxy was exercised with a temporary FastAPI store for orders, shop
context, case creation, and deletion (204 followed by 404). Physical phone
and real-judge verification remain team checkpoints.

Verified locally on the shared baseline: 109 Python tests passed, TypeScript
and the production build passed, and Chrome exercised the role flows and six
review regressions. The repository-wide check stopped at Ruff formatting in
three unchanged judge files (integrity and its test, plus the privacy test).
This local checkpoint still needs the team's green CI and seam review before merge.
