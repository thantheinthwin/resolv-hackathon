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
