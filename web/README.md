# Unboxing Judge web desk

Run `make setup` at the repository root. For the integrated API, set the same
`DEMO_PASSCODE` for Next and FastAPI, then run `make dev`. Sign in to the
integrated demo as `demo` with that passcode. Use HTTPS for shared deployments.
`API_BASE_URL` overrides the default FastAPI origin on port 8000.
`npm run gen:api` regenerates the shared TypeScript types from OpenAPI.

For a sample walkthrough, use Node 22.13 or later, leave the API origin and
passcode unset, and run `npm run dev` here. The desk stores sample cases under
`data/web-sample`. It calls the repository's Python 3.12 environment with
FFmpeg, ffprobe and the OpenCV dependency installed by the shared setup.
The sample judge returns an unassessed verdict. Sample mode uses a shared
demo identity and is intended for local rehearsal with synthetic evidence.

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
   public product links, item confirmation, mixed uploads, original video
   playback, and the product-scoped case sidebar at desktop and phone widths.

Set `INTEGRATED_REHEARSAL_URL` and `INTEGRATED_REHEARSAL_PASSCODE` for a web instance
backed by an isolated FastAPI store to verify browser authentication, token-only
phone upload, and draft-only deletion through the proxy. Physical phone and
real-judge verification remain team checkpoints.

On the rebased branch, `make check` passed all 232 Python tests plus the web
lint, format, and type checks. The Next.js production build passed. The
mobile rehearsal used iPhone and Android profiles in Chrome.

## One-page sample walkthrough

Each shop item has a shop detail page at `/shop/products/[id]` and a public page at `/products/[id]`. Choose **Copy product link** in the shop. A shopper pastes it into **Product link**, chooses **Find my item**, confirms the item, and describes what happened. **Report a problem** on the public page also opens that confirmation.

The shopper attaches one unboxing video and optionally up to three photos on desktop or phone. Shop review shows the video and photos together. Existing order-backed cases retain their purchase details. Product-link claims reference the catalog item only. Sample mode uses a shared demo buyer and fixture verdicts.

## Mobile redesign handoff

- **Voice transcription** is a follow-up. Start with **Dictate description**, let the buyer review
  and edit the text, then submit the report. Agree on Thai and English support, microphone
  permission handling, and how audio is processed and retained. The optional description field
  also accepts the phone keyboard’s dictation where available.
- Photo-only claims remain a follow-up.
