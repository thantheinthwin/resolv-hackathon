import { listProducts } from "../../lib/public-product";
import { productPath } from "../../lib/product-links";

export const dynamic = "force-dynamic";

export default async function Catalog() {
  const products = await listProducts();
  return (
    <main className="desk-content">
      <section className="panel product-details">
        <h1>Browse products</h1>
        {products.length === 0 && <p>The shop hasn’t added any products yet.</p>}
        <ul className="product-list" aria-label="Shop products">
          {products.map((item) => (
            <li key={item.id}>
              <a className="product-row" href={productPath(item.id)}>
                {item.photos.length > 0 && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    className="order-photo"
                    alt=""
                    loading="lazy"
                    src={productPath(item.id) + "/photos/0"}
                  />
                )}
                <span className="product-row-text">
                  <strong>{item.title}</strong>
                  <span>{[...item.colors, ...item.sizes].join(" · ")}</span>
                </span>
                <span className="product-price">฿{item.price.toLocaleString("en-US")}</span>
              </a>
            </li>
          ))}
        </ul>
        <a className="text-link" href="/orders#my-reports">
          My reports
        </a>
      </section>
    </main>
  );
}
