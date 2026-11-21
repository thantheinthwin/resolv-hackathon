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

Use [the planned models and routes](PLAN.md#6-data-and-contracts) for design and the running API schema at `/openapi.json` for implemented HTTP operations. The setup baseline exposes sample case routes, the shared models, a sample verdict, the client generator, and `make check`. Upload operations are documented in OpenAPI and return 501 until the next integration checkpoint. Report missing checks explicitly.

| Boundary | Producer check | Consumer check |
| --- | --- | --- |
| Judge → API | Validate the returned verdict and persisted JSON with the same Pydantic Verdict model. Assert that they serialize to the same data. | Load the sample verdict through FakeJudge and the API read path. Exercise both clear and unsure outcomes. |
| API → web | Exercise the changed route with its documented request, response, and error status. Check the buyer response excludes shop-only fields. | Regenerate types from that API and type-check the consuming screen. For upload or live progress changes, exercise multipart rejection or the SSE event sequence through completion. |

For each changed boundary, identify the producer and consumers in the PR. Record the fixture, command, and result on each side. If a companion change is outside your task, name the affected service and coordinate it before merging.
