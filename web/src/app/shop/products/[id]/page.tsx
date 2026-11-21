import { notFound } from "next/navigation";
import { findProduct } from "../../../../lib/public-product";
import { ShopDesk } from "../../../shop-desk";
export const dynamic = "force-dynamic";
export default async function ShopProduct({ params }: { params: Promise<{ id: string }> }) {
  const listing = await findProduct((await params).id);
  if (!listing) notFound();
  return <ShopDesk initialProduct={listing} />;
}
