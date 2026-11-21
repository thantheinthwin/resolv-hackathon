export function apiOrigin() {
  return (
    process.env.API_ORIGIN ||
    process.env.API_BASE_URL ||
    (process.env.DEMO_PASSCODE ? "http://127.0.0.1:8000" : undefined)
  );
}
