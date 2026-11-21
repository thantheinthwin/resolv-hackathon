import assert from "node:assert/strict";
import test from "node:test";
import { runReview, sourceChanges } from "./review.mjs";

test("source filter excludes uploads and reports omitted source patches", () => {
  const changed = { filename: "judge/example.py", patch: "@@ -1 +1 @@\n-old\n+new" };
  const changes = sourceChanges([changed, { filename: "data/example.py" }, { filename: ".env" }]);
  assert.deepEqual(changes.map((file) => file.filename), [changed.filename]);
  assert.throws(() => sourceChanges([{ filename: changed.filename, additions: 5 }]), /omitted/);
  assert.deepEqual(sourceChanges([
    { filename: "data/private.py", previous_filename: changed.filename },
    { filename: changed.filename, previous_filename: "data/private.py" },
  ]), []);
});

for (const status of ["completed", "failed", "idle"]) {
  test(`agent turn ${status}`, async () => {
    const stream = {
      controller: new AbortController(),
      withResultCollection() {},
      async *[Symbol.asyncIterator]() { yield { type: "agent.session.turn." + status }; },
      async finalResult() { return { output_text: "Review result" }; },
    };
    const create = async (request) => {
      assert.deepEqual(request.environment, { type: "none" });
      assert.equal(request.input, "diff");
      return stream;
    };
    const result = runReview({ beta: { agents: { sessions: { create } } } }, "diff", "rubric", "model");
    if (status === "completed") assert.equal(await result, "Review result");
    else await assert.rejects(result);
    assert.ok(stream.controller.signal.aborted);
  });
}
