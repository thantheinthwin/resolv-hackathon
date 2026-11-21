# FastAPI service

Follow the [root rules](../AGENTS.md). Thant owns the API. Read [service contracts](../docs/CONTRACTS.md) before changing a route, event, or shared model.

- For HTTP changes, compare the route with [the API plan](../docs/PLAN.md#7-api), inspect its OpenAPI schema, and verify the [web client](../web/AGENTS.md) consumes it. Exercise buyer and shop responses separately so verdict details stay shop-only.
- For verdict changes, use the shared model to read the [judge](../judge/AGENTS.md) output and its sample fixture. Keep FakeJudge and real judge results interchangeable.
- Report provider and consumer check results for each affected boundary.
