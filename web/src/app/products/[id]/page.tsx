import { notFound } from "next/navigation";
import { findProduct } from "../../../lib/public-product";
import { productPath } from "../../../lib/product-links";
import { ListingOverview } from "../../products";
export const dynamic = "force-dynamic";
export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const item = await findProduct(id);
  if (!item) notFound();
  const listing = { ...item, photos: item.photos.map((_, i) => productPath(id) + "/photos/" + i) };
  return (
    <main className="desk-content">
      <article className="panel product-details">
        <a className="text-link" href="/products">
          All products
        </a>
        <h1>{listing.title}</h1>
        <ListingOverview listing={listing} />
        <h2>Need help with this item?</h2>
        <p>Tell the shop what happened. We’ll include this item for you.</p>
        <a className="text-link" href={"/orders?product=" + encodeURIComponent(id)}>
          Report a problem
        </a>
      </article>
    </main>
  );
}
