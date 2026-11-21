# Web interface

Use Node 22.12 or later. Run `npm ci` here, then start the Case API on port 8000.
Set the same `DEMO_PASSCODE` in the API and web environments. The orders page
requests data on the Next.js server so the passcode stays on the demo laptop.

Run `npm run gen:api` to update `src/api/types.ts` from the running API, then
`npm run dev` and open <http://localhost:3000>. Use `OPENAPI_URL` to override
the schema URL and `API_BASE_URL` to override the Case API origin.

Run `npm run lint`, `npm run format:check`, `npm run typecheck`, and `npm run build`
to verify the web application.
