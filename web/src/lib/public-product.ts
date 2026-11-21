import "server-only";
import sharp from "sharp";
import { apiOrigin } from "./api-origin";
import type { Listing } from "./models";

async function catalogRead(parts: string[]) {
  const origin = apiOrigin();
  if (!origin) {
    const { sample } = await import("./sample");
    return sample(new Request("http://localhost/api/" + parts.join("/")), parts);
  }
  return fetch(new URL("/api/" + parts.map(encodeURIComponent).join("/"), origin), {
    headers: { "X-Demo-Passcode": process.env.DEMO_PASSCODE || "" },
    cache: "no-store",
    redirect: "error",
  });
}

export async function findProduct(id: string): Promise<Listing | undefined> {
  const response = await catalogRead(["listings"]);
  if (!response.ok) throw new Error("Couldn’t load the shop catalogue.");
  const products: Listing[] = await response.json();
  return products.find((item) => item.id === id);
}

export async function productPhoto(id: string, position: string) {
  if (!/^[0-2]$/.test(position)) return new Response(null, { status: 404 });
  const listing = await findProduct(id);
  const photo = listing?.photos[Number(position)];
  if (!photo || !/^\/api\/files\/(?:[\w-]+\/)*[\w.-]+$/.test(photo) || photo.includes(".."))
    return new Response(null, { status: 404 });
  const response = await catalogRead(photo.slice(5).split("/"));
  const type = response.headers.get("content-type") || "";
  if (!response.ok || !["image/jpeg", "image/png", "image/webp"].includes(type))
    return new Response(null, { status: 404 });
  const preview = await sharp(Buffer.from(await response.arrayBuffer()), {
    limitInputPixels: 24_000_000,
  })
    .rotate()
    .resize({ width: 1600, height: 1600, fit: "inside", withoutEnlargement: true })
    .jpeg()
    .toBuffer();
  return new Response(new Uint8Array(preview), {
    headers: { "Content-Type": "image/jpeg", "X-Content-Type-Options": "nosniff" },
  });
}
