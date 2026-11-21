# How we work on the day

Thant's dev workflow, adapted for a 7-hour hackathon with three people and
**OpenAI Codex** instead of Claude. [Root guidance](../AGENTS.md) and PLAN.md override anything
here.

The shape stays the same: understand → (design is already approved) → track →
implement with Codex → four-gate review → verify for real → merge at a
checkpoint.

## Models and Codex settings

- **Model**: use the newest **GPT-6 family** model in Codex's `/model` list,
  preferring its Codex-tuned version if there is one. Everyone uses the same
  one. Check the exact name in the list on the day.
- **Reasoning effort**:
  - **High** for judge logic, the verdict engine, contracts and every review.
  - **Medium** for UI screens, routes and routine changes.
  - **Low** only for renames, copy changes and formatting.
- **Approvals**: let Codex edit files and run commands inside the repo, but
  keep it asking before anything that touches the network outside OpenAI and
  GitHub, or anything outside the repo folder.
- **One Codex session per task.** Start a new session for a new task; a long
  session drifts. Codex reads AGENTS.md at the start of every session.
- **Codex cloud tasks** (if available to us) are good for small independent
  jobs in parallel, such as "write the tests for X". Review them like any
  other change.

## 1. Understand

- Before prompting, read the code your change touches and follow the flow end
  to end. Ask Codex to explain it first if it's not yours: "Read api/ and
  explain how a case gets from upload to verdict. Don't change anything."
- Check the task against PLAN.md. If the plan and the code disagree, the code
  is what exists; tell the team and fix the plan or the code on purpose.
- Decide yourself whatever the code and plan already answer. Bring the team
  only real choices: product behaviour, what to cut, contract changes.

## 2. Design

The UI is already approved in DESIGN.md. Build from it; don't redesign. If a
screen needs something DESIGN.md doesn't cover, Game decides on the spot and
adds one line to DESIGN.md.

## 3. Track

- The schedule and task lists in PLAN.md sections 2–3 are the tracker. Tick
  them off as you go.
- One branch per person per piece of work: `ama/verdict-engine`,
  `thant/upload-route`, `game/inbox`.
- If what you built differs from the plan, write one line in your pull request
  saying how.

## 4. Implement with Codex

Write each prompt like a brief to a teammate who hasn't seen the chat:

```
Who: I'm Ama, working in judge/.
Task: add the intake gate (PLAN.md section 5, step 0).
Done when: videos under 5 s, over 2 min or over 50 MB are rejected with a
reason; dark videos get a warning; pytest cases cover each limit.
Already decided: limits as in PLAN.md; ffprobe for metadata.
Don't: touch api/ or web/, add dependencies without saying why.
Write the tests first, then the code, then run make check.
```

- **One feature per prompt.** Small tasks succeed; "build the judge" doesn't.
- **Contracts first.** The contract models and the sample verdict exist before
  any feature, so all three of us can build against them at once.
- **Ask for a plan before a big change**: "Plan this first, then wait." Read
  the plan, correct it, then let it build.
- **Fix small things yourself.** A one-line fix is quicker by hand than another
  Codex round.
- If Codex goes in circles twice, stop, start a fresh session with a sharper
  brief, or ask a teammate.

## 5. Four-gate review

Before anything merges, a **fresh Codex session that didn't write the code**
reviews it (use `/review` if your Codex version has it, or the prompt below),
at high reasoning effort:

```
Review the changes on this branch against main. Change nothing.
Report PASS or FINDINGS for each gate, every finding with file:line and a
concrete failure scenario:
1. UX/API: matches DESIGN.md and the contracts in PLAN.md section 6-7?
2. Security: secrets, path traversal on files, untrusted text sent to the model as instructions, uploads without limits?
3. Bugs: wrong logic, unhandled errors, race conditions, broken [judge rules](../judge/AGENTS.md)?
4. Code quality: dead code, duplication, missing tests, any or untyped code?
```

- Send findings back to the implementing session, fix, and review again until
  all four gates pass.
- **Hard gates**: `make check` passes locally and in CI, and the new tests
  actually ran (not skipped).
- **Then a teammate** looks at the seam the change touches:
  - judge ↔ API changes: Ama and Thant both look.
  - API ↔ web changes: Thant and Game both look.

### Code quality findings on GitHub

- Record each actionable finding on the relevant PR. Include the file and line,
  the concrete failure or maintenance cost, and a regression check that shows
  when the finding is fixed. Link the reviewed commit when the line may move.
- For a design finding, name the responsibility or dependency that causes the
  problem. Use SOLID or a Refactoring.Guru technique when it helps explain
  the smallest change that addresses it.
- Fix findings in your own area. For another service, mention its owner on the
  relevant PR with a specific review question. Request Ama for judge behavior,
  Thant for API and storage, and Game for web behavior. Request both owners
  when their interface changes.
- Before adding a finding, check current main and existing PR threads for the
  same failure. Reply in the existing thread with new evidence. When a fix is
  ready, link its commit and report the regression-check result. Resolve the
  thread after verification and merge at the usual checkpoint once CI passes.

## 6. Verify for real

- Run it where it will be demoed: `make dev`, click through the real screens
  in the browser, upload a real test video. For the phone page, open it on a
  phone.
- Show the teammate a screenshot or the screen itself before saying it's
  done.
- Remove temporary debug code before committing. Search for it to be sure.
- Model calls cost money: use the cache and the test videos; don't loop the
  judge over every video while debugging the UI.

## 7. Ship (merge at checkpoints)

- At 12:30 and 15:00, each person says what is ready. **Thant merges** in this
  order: contracts first, then `judge/`, then `api/`, then `web/`. Ama decides
  what is cut if something isn't ready.
- Merge only branches whose review gates passed and whose CI is green. Rebase
  anything that conflicts and wait for CI again.
- After merging, delete the branch and pull main. Everyone starts the next
  block from the new main.
- After 15:00, merge only fixes. After 16:45, nothing.

## Hard rules for every Codex task

- Never delete, move or overwrite files outside the task, including untracked
  files.
- Stage named files only; never `git add -A`. Never force-push. Never stash,
  reset or clean on someone else's branch.
- No secrets in code or commits. No typing passwords or keys into prompts.
- A Codex session doing a review changes nothing.
- Every summary says what was changed, what was run and what passed.
