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
- Upload jobs sample and sanitize the recording and run local integrity checks.
  With no reviewed model inputs, comparisons stay unclear. The seeded sample
  case still uses the fixture.
- For model-backed judging, create the case, configure the judge as described
  in [judge security](../judge/SECURITY.md), then run
  `.venv/bin/python -m api.review_video CASE_ID VIDEO` on the API host before
  uploading. Inspect the sanitized frames, listing photos and order details and
  approve each requested scope, including observation, complaint and reason text. Decline if
  personal data remains. Use only consented recordings. The job reuses this
  reviewed result for the same case, recording and catalog inputs. Another
  recording takes the local-only path. Without a grounded opening observation
  the seal remains unclear and the verdict requires human review.
- Evidence paths in a verdict are relative to `/api/files/cases/{case_id}/`.
  The protected file route serves only the images referenced by that verdict.
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

Product-link claims carry exactly one of `listing_id` or `order_id`. A listing reference identifies the catalog item and never proves a purchase or variant. Listing-only video jobs use local integrity checks; model comparison requires a verified order and the existing human reviews. Migration 0004 preserves existing order-based cases.

Both upload endpoints accept one multipart `video` (5–120 seconds) plus zero to three repeated `photos` files. JPEG, PNG and WebP photos are bounded to 10 MB and 24 megapixels each. All evidence together is bounded to 50 MB, plus 64 KiB for multipart framing. The shop case returns `buyer_photo_count`. Authenticated `GET /api/shop/cases/{id}/photos/{position}` returns a metadata-free JPEG for human review (zero-based). The buyer status response excludes evidence details.

For a verified order, pass repeated `--photo PATH` arguments to `api.review_video` in upload order. The reviewed result binds to the exact video, photos, case and catalog inputs. Uploading other evidence uses local checks. The host’s reviewed multimodal findings are stored in `submission.json` separately from timed video evidence.
