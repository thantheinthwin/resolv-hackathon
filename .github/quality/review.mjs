import { execFileSync } from "node:child_process";
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { join, posix } from "node:path";
import { pathToFileURL } from "node:url";

const { GH_REPO, PR_NUMBER, HEAD_SHA, RUNNER_TEMP } = process.env;
const endpoint = `repos/${GH_REPO}/pulls/${PR_NUMBER}`;
const isSource = (name) =>
  /^(api|judge|web|scripts|\.github\/quality)\/.+\.(py|tsx?|jsx?|mjs|css|sh)$/.test(name) &&
  !/(^|\/)(node_modules|vendor|dist|build|generated|__generated__)\//.test(name);
const gh = (...args) =>
  execFileSync("gh", args, { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });

const reviewMarker = "<!-- resolv-quality-review-v1 -->";

function currentPR() {
  const pr = JSON.parse(gh("api", endpoint));
  if (pr.draft || pr.state !== "open" || pr.head.sha !== HEAD_SHA ||
      pr.head.repo?.full_name !== GH_REPO || pr.base.ref !== "main") {
    return null;
  }
  return pr;
}

function alreadyReviewed() {
  const pages = JSON.parse(gh("api", "--paginate", "--slurp", endpoint + "/reviews?per_page=100"));
  return pages.flat().some((review) => review.commit_id === HEAD_SHA &&
    review.user.login === "github-actions[bot]" && review.body.startsWith(reviewMarker));
}

export function sourceChanges(files) {
  return files.filter((file) => isSource(file.filename) && (!file.previous_filename || isSource(file.previous_filename)))
    .map(({ filename, previous_filename, patch, additions, deletions }) => {
      if (!patch && (additions || deletions)) throw new Error("GitHub omitted a source patch.");
      return { filename, previous_filename, patch };
    });
}

function collect() {
  const pr = currentPR();
  if (!pr) return;
  const files = JSON.parse(gh("api", "--paginate", "--slurp", endpoint + "/files?per_page=100")).flat();
  if (files.length !== pr.changed_files) throw new Error("Incomplete PR file list.");
  const changes = sourceChanges(files);
  if (!changes.length || !currentPR() || alreadyReviewed()) return;
  if (JSON.stringify(changes).length > 100_000) throw new Error("Source patch exceeds review limit.");

  // Read only committed blobs from the trusted checkout, including existing callers.
  const context = {};
  let remaining = 60_000;
  const names = execFileSync("git", ["ls-tree", "-rz", "--name-only", "HEAD"], { encoding: "utf8" });
  const tracked = names.split("\0").filter(isSource);
  const changed = changes.map((file) => file.filename);
  const directories = new Set(changed.map((name) => posix.dirname(name)));
  const services = new Set(changed.map((name) => name.split("/")[0]));
  const related = tracked.filter((name) => services.has(name.split("/")[0]));
  const candidates = new Set([...changed, ...related.filter((name) => directories.has(posix.dirname(name))), ...related]);
  for (const name of candidates) {
    if (!tracked.includes(name)) continue;
    const blob = `HEAD:${name}`;
    const size = Number(execFileSync("git", ["cat-file", "-s", blob]));
    if (size > remaining || size > 20_000) continue;
    context[name] = execFileSync("git", ["cat-file", "blob", blob], { encoding: "utf8" });
    remaining -= size;
  }
  writeFileSync(join(RUNNER_TEMP, "quality-input.json"), JSON.stringify({ changes, baseSources: context }));
  appendFileSync(process.env.GITHUB_ENV, "REVIEW_READY=true\n");
}

export async function runReview(client, input, instructions, model) {
  const events = await client.beta.agents.sessions.create({
    agent: { model, instructions },
    environment: { type: "none" },
    input,
    stream: true,
  });
  events.withResultCollection();
  try {
    let completed = false;
    for await (const event of events) {
      if (/\.(failed|cancelled)$/.test(event.type)) throw new Error("Agent review failed.");
      if (event.type === "agent.session.turn.completed") completed = true;
    }
    const result = await events.finalResult();
    if (!completed || !result.output_text?.trim()) throw new Error("Incomplete agent review.");
    return result.output_text.trim();
  } finally {
    events.controller.abort();
  }
}

async function review() {
  if (!process.env.OPENAI_API_KEY) throw new Error("Set OPEN_AI_CODE_QUALITY_REVIEWER_KEY in the quality-review environment.");
  const { default: OpenAI } = await import("openai");
  const input = readFileSync(join(RUNNER_TEMP, "quality-input.json"), "utf8");
  const instructions = readFileSync(new URL("./rubric.md", import.meta.url), "utf8");
  const result = await runReview(new OpenAI({ maxRetries: 0 }), input, instructions, process.env.OPENAI_MODEL);
  writeFileSync(join(RUNNER_TEMP, "quality-result.txt"), result);
}

function publish() {
  if (!currentPR() || alreadyReviewed()) return;
  const result = readFileSync(join(RUNNER_TEMP, "quality-result.txt"), "utf8");
  const body = reviewMarker + "\n### Advisory code-quality review\n\n" +
    result.slice(0, 25000).split(/\r?\n/).map((line) => "    " + line).join("\n");
  const payload = join(RUNNER_TEMP, "quality-review.json");
  writeFileSync(payload, JSON.stringify({ commit_id: HEAD_SHA, event: "COMMENT", body }));
  gh("api", "--silent", "-X", "POST", endpoint + "/reviews", "--input", payload);
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  await ({ collect, review, publish })[process.argv[2]]();
}
