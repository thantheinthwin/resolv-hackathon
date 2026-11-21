# Unboxing Judge: plan for 21 Nov

Sea x OpenAI Codex Hackathon. Everything here is a written plan. All code is
written on the day with Codex.

## 1. The product in one paragraph

A buyer complains about an order and uploads an unboxing video. Unboxing Judge
checks the video against the order and the shop's listing, looks for signs of
tampering, and gives the shop owner a verdict with evidence: buyer is right,
seller is right, or unsure. Every finding points at a moment in the video,
beside the listing photo, with the reason in English and Thai. The shop owner
agrees or disagrees and makes the final call. The buyer only sees the status
and the shop's note.

**Pitch line:** evidence informs, people decide.

## 2. Team

| Person | Role | Owns | Also |
|---|---|---|---|
| **Ama** | **Team lead.** The judge worker, the core service | `judge/`, the test set, `score.py` | Decides judge behaviour and what gets cut. Answers judges' questions on accuracy |
| **Thant** | Architecture and backend. Puts it all together | `api/`, repo setup, CI, merges into main | Runs the first hour. Drives the demo laptop |
| **Game** | Presenter. UI in the rest of the time | `web/`, slides, demo script | Presents to the judges |

### What each person builds

**Ama: `judge/`**
1. `judge.run(case_dir) -> Verdict`, callable from the command line on a video
   file, returning the sample verdict at first.
2. Intake gate, sampling, integrity checks (code, no model).
3. Listing-match model calls with strict JSON output, in parallel.
4. Grounding check and verdict engine with the rules in section 5.
5. Evidence pack: frame and listing-photo pairs, Thai and English reason.
6. `score.py` over the test cases: accuracy and fraud recall.

**Thant: `api/` and integration**
1. Repo, AGENTS.md, folders, Makefile, CI, branch protection (first hour).
2. `contracts.py`, FastAPI routes from section 7 with sample data, `FakeJudge`.
3. SQLite, video upload to `data/`, background job runner, live status (SSE).
4. Swap `FakeJudge` for Ama's `judge.run`. Shop decision route.
5. Demo passcode, daily case cap, model answer cache.
6. Laptop backup copy, demo videos pre-judged.

**Game: `web/`, slides and pitch**
1. Next.js app with types generated from the API.
2. Buyer screens on sample data: role picker, Your orders, Complaint, Video,
   Sent, My reports.
3. Shop screens: Inbox, Case (verdict, video timeline, evidence, under the
   hood), Decision, Products.
4. Phone upload page opened by QR code.
5. Slides and demo script, a recorded backup demo video.

## 3. Schedule

Organisers' agenda: doors 8:30, opening 9:20, hacking 10:00, working lunch
12:30, **code freeze and submission 17:00**, dinner and round-one judging
17:15 (teams present in rotation), finalists 19:30, awards 20:30, end 21:00.

| Time | Ama | Thant | Game |
|---|---|---|---|
| 8:30–10:00 | Arrive, breakfast, opening. Laptops on, Wi-Fi, GitHub access, Codex signed in. Re-read sections 5–7 together | same | same |
| 10:00–10:45 **Setup** | Check each first-hour result; collect 3–5 test videos | Runs the first-hour prompts (section 8) | Check each result; outline the slides |
| 10:45–12:30 **Build 1** | `judge.run` from the command line; intake, sampling, integrity | API + SQLite, upload, job with `FakeJudge`, SSE | Buyer and shop screens on sample JSON |
| **12:30 checkpoint** | A fake verdict flows end to end: screen → API → job → screen. Merge all three branches | | |
| 12:30–15:00 **Build 2** (working lunch) | Model checks, grounding, verdict engine, `score.py` | Plug in the real judge, decision route, passcode, caps, cache | Screens on the real API, QR upload page, evidence view, start slides |
| **15:00 checkpoint** | A real video is judged in the app and the shop sees it. **Feature freeze** | | |
| 15:00–16:45 **Test + fix** | Tune thresholds, accuracy numbers for the pitch | Fix bugs, laptop backup, pre-judge demo videos | Polish, slides, demo script, backup video |
| **16:45** | Submit. 15 minutes buffer before the 17:00 freeze | | |
| 17:15–19:30 Judging | Answers judge and accuracy questions | Drives the demo laptop | Presents |
| 19:30–21:00 | Finalist pitch if selected, awards, close | | |

Rules: each person on their own branch, `main` always runs, merge only at a
checkpoint, 5-minute stand-up at each checkpoint, nothing new after 15:00.

### Cut list, in this order, if behind at 12:30 or 15:00

1. Seller's packing video cross-check (already out of scope unless ahead).
2. Counterfeit check.
3. Thai reason (keep English).
4. QR phone page (fall back to a file upload on the desktop).
5. Products screen (seed listings from a file instead).

Never cut: the verdict rules in section 5, the evidence timeline, the buyer
not seeing the verdict.

## 4. Architecture

```
Next.js web app ──HTTP + SSE──> FastAPI Case API ──background task──> judge.run()
  buyer + shop screens            routes, SQLite, uploads             ffmpeg, OpenCV,
  phone upload page               live status, cache                  OpenAI vision
                                        │                                   │
                                        └──── data/cases/{id}/ (video, frames, steps, verdict.json)
```

- **web/**: Next.js, TypeScript, desktop only (1024 px and wider) except the
  phone upload page.
- **api/**: FastAPI, Python 3.12, SQLite, files on local disk under `data/`.
  Starts the judge as a background task in the same process (no Redis), at
  most 2 at once, heavy work in a thread.
- **judge/**: a Python package the API imports. Also runs on its own from the
  command line, so Ama can work without the API.
- **OpenAI**: vision model with structured outputs (strict JSON schema).
  `OPENAI_MODEL` sets the model. Answers cached on disk.
- Runs from one laptop for the demo, with a second laptop as backup.

## 5. The judge

### Four questions, in order

1. **Can the video be trusted?** Code checks for cuts, the seal in the first
   seconds, and the parcel label against the order ID. Any failure makes the
   verdict unsure.
2. **What does the video show?** The model describes product, colour, size,
   count and damage **without seeing the complaint**.
3. **Does that match what the shop sent?** Each observation is compared with
   the listing photos and order: match, mismatch or unclear, with a timestamp.
4. **Does the mismatch support the complaint?** The claim type decides which
   check weighs most.

### Pipeline

| Step | What happens | Starting values |
|---|---|---|
| 0 · Intake gate | ffprobe: length, size, rotation, creation time. Reject at once with a reason the buyer sees | Under 5 s, over 2 min or over 50 MB is rejected. Over 40% dark frames: ask to re-record |
| 1 · Sampling | Decode at 2 fps, small greyscale frames. Score blur, brightness, motion, pHash. Keep 1 per second plus scene changes, drop blurry and duplicates, cap at 30, export at 768 px | Blurry: Laplacian variance < 60 at 320 px. Duplicate: pHash distance ≤ 6. Scene change: ffmpeg score > 0.3 |
| 2 · Integrity | Cuts: frame jump with no motion blur. One model call reads tape state and order ID from the first 10 s; code compares the ID | Cut: difference > 4× rolling median and pHash distance ≥ 20. ID match allows one misread character; skipped if no ID is readable |
| Frame router | Opening moment = biggest scene change after the tape is cut. Early frames to seal/label, later frames to product checks, sharp close-ups to damage | 2–4 listing photos per check |
| 3 · Listing match | Up to 5 model calls in parallel: same product, variant (colour, size), contents count, damage, counterfeit signs. Each answers pass / flag / unclear, confidence, timestamps, one-line finding | Timeout 20 s; invalid JSON retried once, then unclear |
| Grounding | Drop findings that cite a time the model was not sent (tolerance 0.05 s). A flag with no grounded finding becomes unclear | |
| 4 · Verdict engine | Fraud flags first. Weigh checks by claim type. Lower confidence for blur, darkness, item never fully shown | Warm light: colour check capped at 0.70 |
| 5 · Evidence pack | Pair each flagged frame with the closest listing photo. One text-only model call writes the Thai and English reason from the findings | |

Target: verdict within 60 s of upload for a one-minute video.

### Verdict rules (these are the spec; port them as tests first)

- **Clear** = leaning is buyer or seller, AND confidence ≥ 0.90, AND no fraud
  flag (tamper or cut), AND the claim is not counterfeit.
- Clear + buyer leaning → `buyer_right`. Clear + seller leaning →
  `seller_right`. Anything else → `needs_human`, shown as **unsure**.
- Unsure still shows the leaning, e.g. "buyer is right, 0.78, unsure".
- Confidence = the lowest of the claim-type step, the seal check and the
  deciding check.
- Reason text adds "Confidence is below 90%." when that is why it is unsure.
- Continuity with no cuts: "No strong scene change in the sampled frames. This
  does not prove the video is unedited."

Test cases to write first (from our earlier 32 tests):
- Confident deciding flag → clear `buyer_right`.
- Exactly 0.90 pass → clear `seller_right`; exactly 0.90 flag → clear
  `buyer_right`.
- 0.89 → keeps the leaning, `needs_human`, unsure, mentions below 90%.
- Fraud flag at confidence 1.0 → unsure.
- A visual cut → unsure.
- Counterfeit claim at confidence 1.0 → unsure.
- Unclear deciding check at 0.99 → unsure.
- Finding at an unsent time is dropped; a grounded one snaps to the sent time.
- Flag with no grounded finding → unclear, so the verdict is unsure.
- A check with no findings is unchanged by grounding.

### Claim types

| Claim | Deciding check |
|---|---|
| `wrong_item` | Same product, then variant |
| `missing` | Contents count |
| `damaged` | Damage |
| `counterfeit` | Counterfeit signs (always unsure) |

## 6. Data and contracts

All in `api/app/contracts.py` (Pydantic). Times in seconds, confidence 0–1.

**Listing**: `id`, `title`, `description` (≤ 1,500 chars), `box_contents[]`,
`price`, `colors[]`, `sizes[]`, `photos[]` (1–3 URLs, first is main).

**Order** (from `data/seed/orders.json`, no entry screen): `id` (printed on
the parcel label), `listing_id`, `variant {color, size}`, `quantity`,
`delivered_at`, `buyer_name` (made up).

**Case**: `id`, `order_id`, `claim_type`, `description`, `status`
(`awaiting_video` | `checking` | `ready` | `decided` | `failed`),
`created_at`, `video_url`, `verdict?`, `decision?`, `progress[]`.

**Verdict** (`verdict.json`):

```json
{
  "case_id": "UJ-48213",
  "verdict": "buyer_right",
  "display": "clear",
  "leaning": "buyer",
  "confidence": 0.94,
  "flags": [{ "type": "cut", "t": 31.5, "note": "sudden jump" }],
  "checks": {
    "seal":       { "status": "pass", "confidence": 0.97, "findings": [] },
    "listing":    { "status": "flag", "confidence": 0.94,
                    "findings": [{ "t": 42.0, "note_en": "Navy; listing is Midnight Black", "note_th": "สีกรมท่า แต่ในประกาศเป็นสีดำ" }] },
    "damage":     { "status": "pass", "confidence": 0.91, "findings": [] },
    "continuity": { "status": "pass", "confidence": 1.0, "findings": [],
                    "note_en": "No strong scene change in the sampled frames. This does not prove the video is unedited." }
  },
  "evidence": [{ "t": 42.0, "check": "listing", "result": "flag",
                 "frame": "frames/0042.jpg", "listing_photo": "listing/1.jpg" }],
  "reason": { "en": "You received navy. You ordered black.", "th": "ได้รับสีกรมท่า แต่สั่งสีดำ" },
  "steps": [{ "name": "sampling", "kind": "code", "seconds": 4.1, "output": "28 frames" }]
}
```

`flags` is empty when there is no fraud signal. The example shows the shape of
one.

**Decision**: `choice` (`agree` | `disagree` on a clear verdict;
`side_buyer` | `side_seller` on an unsure one), `reason` (required for
`disagree`, from: wrong colour seen, item is complete, damage was there
before, video unclear, other), `note_for_buyer` (optional).

**Buyer status** (what the buyer sees): `sent` → `checking` → `with_shop` →
`replied`, plus the shop's note. Never the verdict.

## 7. API

All under `/api`. Every request carries the header `X-Demo-Passcode`. One demo
shop, so no shop ID in paths.

| Method and path | Who | Does |
|---|---|---|
| `GET /orders` | Buyer | Delivered orders with their listing |
| `POST /cases` | Buyer | `{order_id, claim_type, description}` → case in `awaiting_video` |
| `POST /cases/{id}/video` | Buyer | Multipart upload. Runs the intake gate; 422 with a reason if rejected. Starts the judge |
| `POST /cases/{id}/upload-link` | Buyer | One-time token and URL for the phone page (QR code) |
| `POST /uploads/{token}` | Phone | Same as the video upload, from the phone page |
| `GET /cases/{id}` | Buyer | Buyer status and shop note only |
| `GET /cases/{id}/events` | Both | Server-sent events: step started/finished, then done |
| `DELETE /cases/{id}` | Buyer | Deletes the case, video, frames and cached answers |
| `GET /my/cases` | Buyer | My reports list |
| `GET /shop/cases` | Shop | Inbox: unsure first, then newest. Product, order, claim, verdict, display, confidence, time |
| `GET /shop/cases/{id}` | Shop | Full case with verdict, evidence and steps |
| `POST /shop/cases/{id}/decision` | Shop | Decision body above |
| `GET /listings`, `POST /listings` | Shop | Products table; add one with photos (multipart) |
| `GET /files/{path}` | Both | Frames, listing photos, video (only inside `data/`) |

## 8. First hour (10:00–10:45), Thant at the keyboard

One Codex session, one prompt per step. Ama and Game check each result. Nobody
branches until step 6 is merged.

1. **Repo and rules.** Create the repo, add AGENTS.md, PLAN.md, DESIGN.md,
   WORKFLOW.md, the three folders, `.gitignore`, `.editorconfig`.
2. **Contracts.** "Write `api/app/contracts.py` with the Pydantic models in
   PLAN.md section 6, and `judge/fixtures/verdict.sample.json` that validates
   against them, with a test that checks it."
3. **API skeleton.** "FastAPI app with every route in PLAN.md section 7
   returning sample data, SQLite, and a `FakeJudge` behind a `Judge`
   interface."
4. **Web skeleton.** "Next.js app in `web/` with `npm run gen:api` generating
   types from the API's OpenAPI spec, and the role picker and Your orders
   page."
5. **Judge skeleton.** "`judge.run(case_dir)` returning the sample verdict,
   and `python -m judge path/to/video.mp4`."
6. **Quality gate.** "Makefile with setup, dev, check, score. Ruff, pytest,
   ESLint, Prettier, tsc. A GitHub Actions workflow running `make check` on
   pull requests." Then turn on branch protection for `main`.

## 9. Limits and privacy

- Demo passcode on every request; daily cap of 50 cases in total and 10 per
  IP address.
- The complaint, listing text and video text are data to the model, never
  instructions.
- Faces blurred before frames are stored (OpenCV Haar cascade). Parcel labels
  are not blurred: the label check needs them, demo parcels use made-up names.
- Deleting a case deletes its video, frames and cached model answers.
- Only the team's own videos are used. No keys or real buyer data anywhere in
  the repo.

## 10. Demo

- 3 prepared cases, filmed by us with seeded order IDs on the labels:
  1. Wrong colour, clear "Buyer is right".
  2. Item matches the listing, clear "Seller is right".
  3. A cut in the video, "Unsure: check the video" with the cut marked.
- Pre-judge all three before 16:45 so the cache makes the demo instant; judge
  one live if the Wi-Fi is good.
- Show: buyer files a complaint → buyer sees "Sent to the shop" → shop inbox →
  case with the timeline and evidence pair → decision → buyer sees the note.
- Close with the accuracy and fraud-recall numbers from `score.py`.
- Backup: the recorded demo video and the second laptop.
