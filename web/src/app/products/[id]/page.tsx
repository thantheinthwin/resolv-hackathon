import { notFound } from "next/navigation";
import { findProduct } from "../../../lib/public-product";
import { productPath } from "../../../lib/product-links";
import { formatPrice } from "../../../lib/price";
import styles from "../../storefront.module.css";

export const dynamic = "force-dynamic";
export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const item = await findProduct(id);
  if (!item) notFound();
  return (
    <main className={styles.store}>
      <nav aria-label="Product navigation">
        <a className={styles.back} href="/orders">
          ‹ Back to report a problem
        </a>
      </nav>
      <article className={styles.detail}>
        <div className={styles.gallery}>
          {item.photos.map((_, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={i}
              src={productPath(id) + "/photos/" + i}
              alt={item.title + ", photo " + (i + 1)}
            />
          ))}
          {!item.photos.length && <p>Product photo unavailable</p>}
        </div>
        <div className={styles.info}>
          <h1>{item.title}</h1>
          <p className={styles.price}>฿{formatPrice(item.price)}</p>
          {item.description && <p>{item.description}</p>}
          {(
            [
              ["Colours", item.colors],
              ["Sizes or models", item.sizes],
              ["In the box", item.box_contents],
            ] as const
          ).map(
            ([label, values]) =>
              values.length > 0 && (
                <div className={styles.spec} key={label}>
                  <h2>{label}</h2>
                  <ul>
                    {values.map((value, i) => (
                      <li key={i}>{value}</li>
                    ))}
                  </ul>
                </div>
              ),
          )}
          <a className={styles.cta} href={"/orders?product=" + encodeURIComponent(id)}>
            Report a problem
          </a>
        </div>
      </article>
    </main>
  );
}
