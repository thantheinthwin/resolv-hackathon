// Allow a 50 MB video plus multipart headers. Enforce the cap for chunked requests too.
const maxBytes = 51_000_000;
export async function boundedBody(request: Request): Promise<ArrayBuffer> {
  if (Number(request.headers.get("content-length")) > maxBytes) throw new RangeError();
  const reader = request.body?.getReader();
  const chunks: ArrayBuffer[] = [];
  let total = 0;
  while (reader) {
    const { value, done } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      throw new RangeError();
    }
    chunks.push(new Uint8Array(value).buffer);
  }
  return new Blob(chunks).arrayBuffer();
}
