# Development guardrails

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
