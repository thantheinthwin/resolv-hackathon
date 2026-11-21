import { connection } from "next/server";
import { apiOrigin } from "../../lib/api-origin";
import { BuyerDesk } from "../buyer-desk";

export default async function Orders({
  searchParams,
}: {
  searchParams: Promise<{ product?: string | string[] }>;
}) {
  await connection();
  const { product } = await searchParams;
  return (
    <BuyerDesk
      sampleMode={!apiOrigin()}
      linkedProduct={typeof product === "string" ? product : undefined}
    />
  );
}
