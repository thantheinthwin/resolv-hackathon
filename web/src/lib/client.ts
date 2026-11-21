export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  data?: unknown,
  method = data === undefined ? "GET" : "POST",
): Promise<T> {
  const form = data instanceof FormData;
  const res = await fetch("/api/" + path, {
    cache: "no-store",
    method,
    headers: form || data === undefined ? {} : { "Content-Type": "application/json" },
    body: form ? data : data === undefined ? undefined : JSON.stringify(data),
  });
  if (res.status === 204) return undefined as T;
  const result = await res.json();
  if (!res.ok)
    throw new ApiError(
      typeof result.detail === "string" ? result.detail : "Request failed. Please retry.",
      res.status,
    );
  return result;
}
