import { connection } from "next/server";
import { apiOrigin } from "../../lib/api-origin";
import { ShopDesk } from "../shop-desk";

export default async function Shop() {
  await connection();
  return <ShopDesk sampleMode={!apiOrigin()} />;
}
