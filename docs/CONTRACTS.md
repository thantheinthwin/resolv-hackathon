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
  uploading. Inspect the sanitized frames, listing photos and order details at
  the first prompt, and complaint and finding text at the second. Decline if
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
