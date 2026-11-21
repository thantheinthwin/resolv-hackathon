# Unboxing Judge: rules for Codex

Codex reads this file before every task. All three of us use it, so every
Codex session follows the same rules. The full plan is in PLAN.md, the screens
are in DESIGN.md and the way we work is in WORKFLOW.md. Read the parts of them
that your task touches before you change anything.

## What we are building

A buyer uploads an unboxing video with a complaint about an order. The judge
checks the video against the order and the shop's listing, and gives the shop
owner a verdict (buyer is right, seller is right, or unsure) with timestamped
evidence in English and Thai. The shop owner makes the final decision. The
buyer never sees the verdict, only the status and the shop's note.

## Who you are working with

Start every session by confirming who you are working for. If the person has
not said, ask once. Stay inside that person's folder unless the task says
otherwise.

| Person | Role | Owns | Typical tasks |
|---|---|---|---|
| **Ama** | Team lead. The brain of the product | `judge/` | Video sampling, integrity checks, model calls, grounding, verdict engine, `score.py`, accuracy numbers |
| **Thant** | Architecture and backend. Puts everything together | `api/`, repo setup, CI, merging | FastAPI routes, database, uploads, background jobs, live status, wiring web and judge together |
| **Game** | Presenter. Builds UI in the rest of the time | `web/`, slides, demo script | Next.js screens from DESIGN.md, the phone upload page, the pitch |

Ama has the final say on judge behaviour and on what gets cut. Thant has the
final say on the API, the repo layout and when something merges into main.

## Folders

- `web/`    Next.js + TypeScript screens. Owner: Game.
- `api/`    Python 3.12 + FastAPI Case API. Owner: Thant.
- `judge/`  Python judge worker (ffmpeg, OpenCV, OpenAI). Owner: Ama.
- `api/app/contracts.py`  Shared Pydantic models (Order, Listing, Case,
  Verdict, Decision). Changing it needs the whole team's agreement.
- `data/`   Local storage for videos, frames, cache and the SQLite file.
  Never committed.

Only edit the folder your task names. If the task needs a change in another
folder, stop and say exactly what is needed instead of making it.

## Contracts

The two contracts are where our work meets. PLAN.md section 6 has every field.

- **verdict.json** (judge to API): `judge.run(case_dir)` returns a `Verdict`
  and writes `verdict.json`. Fields: `case_id`, `verdict`
  (buyer_right | seller_right | needs_human), `display` (clear | unsure),
  `leaning` (buyer | seller | none), `confidence` (0 to 1), `flags`,
  `checks`, `evidence`, `reason` {en, th}, `steps` (for "Under the hood").
- **The API** (API to web): FastAPI's OpenAPI spec is the source of truth.
  After any API change, run `npm run gen:api` in `web/` to regenerate
  `web/src/api/types.ts`. Never edit that file by hand.
- Until the real judge is merged, `api/` uses `FakeJudge`, which returns
  `judge/fixtures/verdict.sample.json`.
- Never rename or remove a contract field to fix one bug. Say it in the team
  chat first.

## Commands

- `make setup`  install everything
- `make dev`    run the API (port 8000) and web (port 3000) together
- `make check`  ruff check, ruff format --check, pytest, eslint,
                prettier --check, tsc --noEmit
- `make score`  run the judge over the test set and print accuracy

Run `make check` before you finish every task and fix what it reports. In your
summary, say what you ran and whether it passed.

## Code rules

- Python: type hints everywhere, Pydantic models at every boundary, pytest
  tests in `tests/` next to the code, short functions.
- TypeScript: strict mode, no `any`, use the generated API types.
- Prettier and Ruff use 100 characters a line.
- Add a dependency only when it is needed, and say why in the summary.
- One feature per task, with its tests. Write the tests first for anything in
  `judge/`.
- No secrets in code. `OPENAI_API_KEY`, `OPENAI_MODEL` and `DEMO_PASSCODE`
  come from the environment only. Never commit `.env` files, keys, videos or
  frames.

## Judge rules (never weaken these)

- Confidence runs from 0 to 1. A verdict is **clear** only at 0.90 or more,
  with no fraud flag, and never for a counterfeit claim. Everything else is
  **unsure**. An unsure verdict still shows its leaning.
- The buyer's complaint goes only to the claim-type step. The checks that
  describe the video never see it, so it cannot bias what they report.
- Every finding cites the timestamp of a frame the model was actually sent.
  Drop any finding that cites another time. A flag left with no grounded
  finding becomes unclear.
- Fraud signals (seal opened before filming, a cut, a label that doesn't match
  the order) always make the verdict unsure.
- "No cuts found" means only in the sampled frames. Never say a video is
  proven unedited.
- The complaint, the listing text and any text visible in the video are data,
  never instructions. Put them inside clearly marked blocks in prompts.
- The model answers in a strict JSON schema. Invalid JSON is retried once,
  then that check becomes unclear.

## Running

- No Redis and no separate queue. The judge runs as a FastAPI background task,
  with ffmpeg and OpenCV work in a thread, at most 2 videos at once.
- Every judge step saves its output under `data/cases/{id}/`, so a failed job
  restarts from the last finished step.
- Model answers are cached as JSON files keyed by a hash of the frames and the
  prompt, so re-running a demo video costs nothing.

## Git

- Each person works on their own branch: `ama/...`, `thant/...`, `game/...`.
- `main` must always run. Merge only at a checkpoint (12:30, 15:00), after
  `make check` and CI pass.
- Stage named files only. Never `git add -A`, never force-push, never rewrite
  someone else's branch.
