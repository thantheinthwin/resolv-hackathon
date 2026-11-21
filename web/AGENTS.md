# Next.js client

Follow the [root rules](../AGENTS.md). Game owns the web client. Use the [design guide](../docs/DESIGN.md) for screens and [service contracts](../docs/CONTRACTS.md) for API data.

- Check request bodies, error statuses, and response fields against the [API service](../api/AGENTS.md). Once the generator exists, run `npm run gen:api` from this directory and type-check the consuming screens. Keep generated types out of hand-written edits.
- Verify the affected buyer or shop flow with an API response. When changing live status, check event names and payloads against the API stream. Keep shop verdicts and evidence out of buyer views.
