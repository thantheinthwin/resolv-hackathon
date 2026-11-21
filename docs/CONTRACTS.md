# Service contracts

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

## Verify a boundary change

Use [the planned models and routes](PLAN.md#6-data-and-contracts) for design and the running API schema at `/openapi.json` for implemented HTTP operations. The setup baseline exposes sample case routes, the shared models, a sample verdict, the client generator, and `make check`. Desktop and one-time phone uploads share video intake and persisted progress events. Listing creation accepts a multipart form with repeated photo and option fields. Report missing checks explicitly.

| Boundary | Producer check | Consumer check |
| --- | --- | --- |
| Judge → API | Validate the returned verdict and persisted JSON with the same Pydantic Verdict model. Assert that they serialize to the same data. | Load the sample verdict through FakeJudge and the API read path. Exercise both clear and unsure outcomes. |
| API → web | Exercise the changed route with its documented request, response, and error status. Check the buyer response excludes shop-only fields. | Regenerate types from that API and type-check the consuming screen. For upload or live progress changes, exercise multipart rejection or the SSE event sequence through completion. |

For each changed boundary, identify the producer and consumers in the PR. Record the fixture, command, and result on each side. If a companion change is outside your task, name the affected service and coordinate it before merging.

## SQLite schema and upgrades

The [numbered SQL migrations](../api/migrations/) define the schema in `data/cases.sqlite3`.
API startup applies pending files in numeric order in one transaction and records the last
applied number in SQLite's `PRAGMA user_version`. Existing unversioned demo databases start
at version zero. Add a new numbered file for subsequent changes.

- `0001_case_storage.sql` adopts the case, photo, upload-link, recovery and seed tables.
- `0002_products_orders.sql` migrates existing listings into products and creates a delivered
  demo order for each. New listings follow the same flow. Cases reference orders, which
  reference products. Case details and verdicts retain their validated JSON representation.
- `0003_daily_usage.sql` stores Bangkok-day case totals and per-IP counters. On upgrade,
  surviving non-seed cases created that day count toward the global limit. Older databases
  contain no client IP history. A proxy that presents one peer address shares one IP quota.

This aligns the four domain tables (`cases`, `products`, `orders`, `usage`) with the
[prototype schema](https://github.com/thantheinthwin/unboxing-judge/blob/main/db/schema.ts).
The competition API uses one passcode-protected shop, local media storage and SQLite job
claims. The SQL files upgrade competition databases; importing a prototype D1 dump would
require a separate data conversion.
