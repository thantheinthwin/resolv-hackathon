# Repository guidance

Read [development guardrails](docs/DEVELOPMENT.md) and [team workflow](docs/WORKFLOW.md) before editing. They cover ownership, code rules, checks, branches, and merge checkpoints.

Read the guide for each service your task touches, including the other side of a changed interface.

- [Web](web/AGENTS.md) — Next.js screens and API consumption.
- [API](api/AGENTS.md) — FastAPI routes, shared models, and judge integration.
- [Judge](judge/AGENTS.md) — evidence analysis and verdict production.

For cross-service changes, follow [service contracts](docs/CONTRACTS.md). Consult the [project plan](docs/PLAN.md) for behavior and the [design guide](docs/DESIGN.md) for screens.

## Before pushing or opening a PR

Have a fresh, read-only Codex agent review the outgoing diff against the target branch using the [four review gates](docs/WORKFLOW.md#5-four-gate-review). Fix any findings and have the agent review the updated diff. Push or open the PR only after all four gates and local `make check` pass. Include the reviewed commit SHA and both results in the PR description.
