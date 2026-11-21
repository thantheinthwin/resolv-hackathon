import { NextResponse, type NextRequest } from "next/server";
import { apiOrigin } from "./lib/api-origin";
import { integratedAccessError } from "./lib/integrated-access";

export function proxy(request: NextRequest) {
  if (
    request.method === "GET" &&
    /^\/products(?:\/[\w-]+(?:\/photos\/[0-2])?)?\/?$/.test(request.nextUrl.pathname)
  )
    return NextResponse.next();
  const error = apiOrigin() ? integratedAccessError(request) : undefined;
  return error ?? NextResponse.next();
}

// The API route authorizes before reading multipart bodies.
export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"] };
