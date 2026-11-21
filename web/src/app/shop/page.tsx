import { ShopDesk } from "../shop-desk";
export default async function Shop({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  return <ShopDesk showProducts={(await searchParams).view === "products"} />;
}
