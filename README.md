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
verdict for testing the integration. To exercise a new case through the API, submit a multipart
`video` file to `POST /api/cases/{id}/video` and follow
`GET /api/cases/{id}/events`. Accepted uploads enter `checking`; the shop
detail exposes the verdict when the case reaches `ready`. A failed case
accepts a replacement upload. Run one API process per data directory. It
resumes interrupted jobs on startup and runs up to two judges at once.

Run `make check` for the Python and web checks. After changing an API route,
run `npm --prefix web run gen:api` against the running API and check the
generated TypeScript diff.

## Advisory PR quality review

The OpenAI reviewer checks ready, same-repository pull requests into `main` for
duplicated rules, unnecessary abstractions, and responsibilities that are hard
to change independently. The [review rubric](.github/quality/rubric.md) is
versioned with the code. Findings appear as a review on the inspected commit.
The existing competition checks and teammate review still apply.

In GitHub Settings → Environments, use the `quality-review` environment,
restrict deployments to `main`, and add an environment secret named
`OPEN_AI_CODE_QUALITY_REVIEWER_KEY`. Use a dedicated OpenAI project service-account key with
`api.agents.read`, `api.agents.write`, and `api.responses.write`. Set the
optional environment variable `OPENAI_MODEL` to select an Agents API model.

Once both workflows are on `main`, open a source-changing PR or mark one ready
for review. The privileged job reads the PR patch through GitHub and runs the
reviewer from the default branch. It sends source patches and bounded context
to OpenAI. Large or incomplete patches produce a workflow error. Drafts,
forks, and changes outside the supported source paths skip paid inference.
Run `node --test .github/quality/review.test.mjs` for the offline reviewer checks.
