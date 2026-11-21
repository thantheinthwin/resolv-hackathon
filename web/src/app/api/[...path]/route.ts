import { boundedBody } from "../../../lib/request-body";

export const dynamic = "force-dynamic";
const pathRules: Record<string, RegExp> = {
  DELETE: /^cases\/[\w-]+$/,
  GET: /^(orders|my\/cases|cases\/[\w-]+(?:\/events)?|shop\/cases(?:\/[\w-]+)?|listings|files\/[\w./-]+)$/,
  POST: /^(cases|cases\/[\w-]+\/(video|upload-link)|uploads\/[\w-]+|shop\/cases\/[\w-]+\/decision|listings)$/,
};
async function handle(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const parts = (await ctx.params).path,
    route = parts.join("/");
  if (
    parts.some((p) => p === "." || p === ".." || p.includes("/")) ||
    !pathRules[req.method]?.test(route)
  )
    return new Response(null, { status: 404 });
  const origin =
    process.env.API_ORIGIN ||
    process.env.API_BASE_URL ||
    (process.env.DEMO_PASSCODE ? "http://127.0.0.1:8000" : undefined);
  let body: ArrayBuffer | undefined;
  if (req.method === "POST") {
    try {
      body = await boundedBody(req);
    } catch {
      return Response.json({ detail: "Upload exceeds the request size limit." }, { status: 413 });
    }
  }
  if (!origin) {
    const { sample } = await import("../../../lib/sample");
    return sample(
      body ? new Request(req.url, { method: req.method, headers: req.headers, body }) : req,
      parts,
    );
  }
  const headers = new Headers({ "X-Demo-Passcode": process.env.DEMO_PASSCODE || "" });
  for (const key of ["content-type", "accept", "range"]) {
    const value = req.headers.get(key);
    if (value) headers.set(key, value);
  }
  try {
    const upstream = await fetch(
      new URL("/api/" + parts.map(encodeURIComponent).join("/"), origin),
      {
        method: req.method,
        headers,
        body: body,
        cache: "no-store",
        redirect: "error",
        signal: req.signal,
      },
    );
    const out = new Headers();
    for (const key of ["content-type", "content-range", "accept-ranges"]) {
      const value = upstream.headers.get(key);
      if (value) out.set(key, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: out });
  } catch {
    return Response.json(
      { detail: "The case service is unavailable. Please retry." },
      { status: 502 },
    );
  }
}
export { handle as GET, handle as POST, handle as DELETE };
