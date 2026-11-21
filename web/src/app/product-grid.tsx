"use client";

import { Package, Search } from "lucide-react";
import { useState } from "react";
import { productPath } from "../lib/product-links";
import { formatPrice } from "../lib/price";
import type { Listing } from "../lib/models";
import styles from "./storefront.module.css";

function variantSummary(values: string[], term: string, label: string) {
  if (values.length <= 2) return values.join(" · ");
  const match = term && values.find((value) => value.toLocaleLowerCase().includes(term));
  return match ? match + " +" + (values.length - 1) : values.length + " " + label;
}

export function ProductGrid({ products }: { products: Listing[] }) {
  const [query, setQuery] = useState("");
  const term = query.trim().toLocaleLowerCase();
  const visible = products.filter((p) =>
    [p.title, ...p.colors, ...p.sizes].some((v) => v.toLocaleLowerCase().includes(term)),
  );
  return (
    <section className={styles.catalog} aria-label="Browse products">
      <div className={styles.toolbar}>
        <label className={styles.search}>
          <Search size={19} aria-hidden />
          <input
            type="search"
            aria-label="Search products"
            placeholder="Search products or options"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <p className={styles.count} role="status">
          {visible.length} {visible.length === 1 ? "product" : "products"}
        </p>
      </div>
      {visible.length === 0 && (
        <p>
          {products.length
            ? "No items match your search. Try another name or colour."
            : "The shop hasn’t added any products yet."}
        </p>
      )}
      <ul className={styles.grid}>
        {visible.map((item) => (
          <li key={item.id}>
            <a className={styles.card} href={productPath(item.id)}>
              <div className={styles.photo}>
                {item.photos.length ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={productPath(item.id) + "/photos/0"} alt="" loading="lazy" />
                ) : (
                  <Package aria-hidden />
                )}
              </div>
              <div className={styles.caption}>
                <h3>{item.title}</h3>
                <strong>฿{formatPrice(item.price)}</strong>
              </div>
              <p className={styles.options}>
                {[
                  variantSummary(item.colors, term, "colours"),
                  variantSummary(item.sizes, term, "options"),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
