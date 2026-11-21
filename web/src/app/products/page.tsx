import { listProducts } from "../../lib/public-product";
import { ProductGrid } from "../product-grid";
import styles from "../storefront.module.css";

export const dynamic = "force-dynamic";
export default async function Catalog() {
  return (
    <main className={styles.store}>
      <a className={styles.back} href="/orders">
        Report a problem
      </a>
      <h1>Browse products</h1>
      <ProductGrid products={await listProducts()} />
    </main>
  );
}
