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

The integrated web client uses the generated API contracts for both roles.
The buyer view shows the status and shop note. The shop review includes
evidence and the saved decision. The sample adapter calls the team's intake
implementation so phone and desktop uploads share decoding and recording-quality
checks.

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
4. `node scripts/mobile-flow.mjs` checks direct uploads, report evidence, and the
   seller case list with iPhone and Android screen profiles in Chrome. Install
   Playwright WebKit and set `PHONE_WEBKIT=1` to run the iPhone profile in WebKit.
5. `node scripts/product-flow.mjs` checks the product wizard, role switches,
   shared claim links, catalogue search, draft replacement, original video
   playback, and the product-scoped case sidebar at desktop and phone widths.

Set `INTEGRATED_REHEARSAL_URL` to a web instance backed by an isolated FastAPI
store to also verify that draft-only deletion preserves a video after a phone
upload. Physical phone and real-judge verification remain team checkpoints.

On the rebased branch, `make check` passed all 232 Python tests plus the web
lint, format, and type checks. The Next.js production build passed. The
mobile rehearsal used iPhone and Android profiles in Chrome.

## One-page sample walkthrough

From the shop product page, select **Copy claim link** and open it on any
browser that can reach the sample server. In **Find your product**, buyers can
paste the link for an exact match or type a name, variant, or reference for
ranked suggestions. Confirming a product opens the claim fields in the same
section. **Use an existing order** opens the order-based path. **My reports** on the same page includes
the buyer's description, original video, status, and shop reply.

The sample store uses one shared demo buyer. Use sandbox data and rehearsal
clips. Standalone claims follow the exact listing ID, and order-based claims
follow their order's listing ID. Open a claim from a product to see that
product's case list, or from the inbox to see all submitted cases. The
integrated API supports catalogue creation and order-based claims. Standalone
claim intake and authenticated buyer playback are integration follow-ups.

## Mobile redesign handoff

- **Voice transcription** is a follow-up. Start with **Dictate description**, let the buyer review
  and edit the text, then submit the report. Agree on Thai and English support, microphone
  permission handling, and how audio is processed and retained. The optional description field
  also accepts the phone keyboard’s dictation where available.
- **Photo evidence** is a follow-up for buyers who have already opened the parcel. It needs an API
  path for attaching photos and a manual review workflow for cases without video.
