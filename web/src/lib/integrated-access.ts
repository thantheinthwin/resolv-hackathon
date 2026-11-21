import { createHash, timingSafeEqual } from "node:crypto";

function digest(value: Buffer | string) {
  return createHash("sha256").update(value).digest();
}

export function integratedAccessError(request: Request) {
  const { pathname } = new URL(request.url);
  if (
    (request.method === "GET" && /^\/upload\/[\w-]+$/.test(pathname)) ||
    (request.method === "POST" && /^\/api\/uploads\/[\w-]+$/.test(pathname))
  )
    return undefined;

  const passcode = process.env.DEMO_PASSCODE;
  if (!passcode) return new Response("Demo access is not configured.", { status: 503 });

  const credentials = request.headers.get("authorization")?.match(/^Basic ([\w+/]+={0,2})$/i);
  if (
    !credentials ||
    !timingSafeEqual(digest(Buffer.from(credentials[1], "base64")), digest("demo:" + passcode))
  )
    return new Response("Sign in to the integrated demo.", {
      status: 401,
      headers: {
        "WWW-Authenticate": 'Basic realm="Unboxing Judge demo", charset="UTF-8"',
        "Cache-Control": "no-store",
      },
    });

  const origin = request.headers.get("origin");
  if (request.method === "POST" || request.method === "DELETE") {
    if (
      request.headers.get("sec-fetch-site") === "cross-site" ||
      (origin && URL.parse(origin)?.host !== request.headers.get("host"))
    )
      return new Response("Use the demo page to make this request.", { status: 403 });
  }
  return undefined;
}
