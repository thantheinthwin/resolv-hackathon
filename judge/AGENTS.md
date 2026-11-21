# Judge worker

Follow the [root rules](../AGENTS.md). Ama owns the worker. Use [the judge plan](../docs/PLAN.md#5-the-judge) and write verdict-rule tests first.

## Judge rules

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

## API handoff

Follow [service contracts](../docs/CONTRACTS.md) for the return value, saved verdict, and sample fixture. Validate all three with the shared model. Check that the [API consumer](../api/AGENTS.md) can load the result before merging a shape change.

### Connecting the real worker

The integration point is `judge.run(case_dir, inputs, review=..., progress=...)`.
The API's `CaseJudge.prepare` uses it during trusted host review. The
background job keeps its existing `Judge.run(case_dir)` shape and reuses
the matching prepared verdict.

1. Resolve the stored case, order, and listing on the server. Build
   `judge.JudgeInputs` with the case's claim type and description, the matching
   shared `Order` and `Listing`, and one to three `ReviewedListingPhoto` objects
   decoded locally from the listing's stored photos. Mark each photo reviewed
   only after a human checks it. Never take review flags, local paths, or
   these typed inputs from buyer form fields.
2. Keep `case_dir/video.mp4` and the case inputs stable for a job and its
   retries. Pass optional `redactions_by_timestamp` keyed by exact timestamps
   from `judge.sampling.sample_frames`. Supply an optional
   `OpeningObservation` from trusted local inspection or use the
   [local opening reviewer](#local-opening-review). The opening observation
   and order ID stay local. Without it, an unassessed seal forces human review.
3. Install the API requirements, which include `judge/requirements.txt`, and
   set `OPENAI_API_KEY` and `OPENAI_MODEL` in the app process using the
   [local setup guide](SECURITY.md). An injected `client` and `model` allow
   offline tests. The production entry point uses the configured OpenAI client.

The adapter's `review(request: judge.ReviewRequest) -> bool` callback checks a
recorded human approval for the active upload, request stage, and
`request.fingerprint`. Display the request's private `text` and
`images` (reference and JPEG byte pairs) only to the reviewer. Approval
requires an explicit `True` for those exact contents. Keep previews private
and out of logs, buyer responses, and public media routes.

| Review stage | Human reviews | When approval is missing |
| --- | --- | --- |
| `visual` | Sanitized sent frames, reviewed listing photos, and product/order fields used in the comparison | `ReviewRequired` before any model call |
| `observation` | Product observation text that would be reused in the matcher | `ReviewRequired` before comparison calls |
| `complaint` | The written complaint and related finding text | The worker skips transfer and returns an unsure recommendation. The adapter can raise `ReviewRequired(request.stage)` to wait instead. A blank description uses the selected claim type locally. |
| `reason` | Finding text for the deciding check | The worker keeps the deterministic bilingual reason |

The API stores pending reviews and resumes the job after approval of the
same request. Use `python -m api.review_pending CASE_ID` on the API host to
inspect and respond to each pending stage. Successful model results are reused from the private
`.judge-cache/` on retry. Local preparation runs again.

The worker emits shared `ProgressEvent` messages for step start and finish if
given a `progress` callback. Thant owns persistence and final completion in
the API. Publish completion only after `run` returns and the saved
`verdict.json` validates to the same `Verdict`. The worker writes the reviewed
JPEGs under case-relative `frames/` and `listing/` before publishing the
verdict. Serve referenced assets to the shop only. Keep the cache, pending
review data, and unlisted files private. The shop still records the decision.

The ready-to-wire stages are intake, sampling, redaction, integrity,
complaint-blind observation and listing comparison, complaint grounding,
deterministic verdict, exact-timestamp evidence, and bilingual reasons. The
worker uses the same bounded model frame subset for the matcher and evidence
pack. Grounded complaint links put relevant evidence first and scope reason
selection when they match the deciding check. The one-argument
fixture path is for case directories without an uploaded `video.mp4`.

### Local opening review

Run `python -m api.review_video CASE_ID VIDEO` on the host before uploading
the same video. This command passes the interactive opening reviewer to
`CaseJudge.prepare`. Use a fresh case for the first run because the adapter
reuses a matching verdict that was already prepared.

Call this from the operator's local session. The default preview uses a
locally installed `ffplay` window and streams the sampled image through a pipe.
A host viewer can supply `show(frame)` instead. The early previews are private,
may contain unredacted data, and must stay off disk, remote model requests,
logs, and public routes. Close the preview to return to the terminal. Use
`back` to inspect a different frame or press Enter at frame selection to skip.

Use a frame before the buyer begins opening the parcel. Select `intact` or
`opened` only when clearly visible. Select `unclear` when in doubt. Enter a
rectangle in preview pixels that covers the entire label before entering a
visible order code. Enter a blank code to leave the label check unassessed.
The judge uses the actual selected timestamp from the first ten seconds, keeps
the code in memory, and masks that rectangle before the visual approval stage.
Use `redactions_by_timestamp` for any visible label or other PII in additional
frames. All outbound images still need the regular human visual approval.

An existing `inputs.opening` takes precedence over the callback. An adapter
using a previously collected observation must also supply the needed masks.
If the operator skips, or the sampler has no eligible early frame, the worker
continues with the seal unassessed and requires human review.
