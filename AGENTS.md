# Repository guidance

Read [development guardrails](docs/DEVELOPMENT.md) and [team workflow](docs/WORKFLOW.md) before editing. They cover ownership, code rules, checks, branches, and merge checkpoints.

Read the guide for each service your task touches, including the other side of a changed interface.

- [Web](web/AGENTS.md) — Next.js screens and API consumption.
- [API](api/AGENTS.md) — FastAPI routes, shared models, and judge integration.
- [Judge](judge/AGENTS.md) — evidence analysis and verdict production.

For cross-service changes, follow [service contracts](docs/CONTRACTS.md). Consult the [project plan](docs/PLAN.md) for behavior and the [design guide](docs/DESIGN.md) for screens.
