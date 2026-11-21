import { NextResponse, type NextRequest } from "next/server";
import { apiOrigin } from "./lib/api-origin";
import { integratedAccessError } from "./lib/integrated-access";

export function proxy(request: NextRequest) {
  const error = apiOrigin() ? integratedAccessError(request) : undefined;
  return error ?? NextResponse.next();
}

// The API route authorizes before reading multipart bodies.
export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"] };
