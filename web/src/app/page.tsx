import Link from "next/link";
import { ArrowRight, Package, Store } from "lucide-react";

export default function Home() {
  return (
    <>
      <h1>
        Choose your role<span>.</span>
      </h1>
      <div className="roles">
        <section className="card">
          <Package className="role-icon" aria-hidden="true" />
          <h2>Buyer</h2>
          <p>Report a problem with a delivered order and share your unboxing video.</p>
          <Link href="/orders" className="button">
            View your orders <ArrowRight size={18} aria-hidden="true" />
          </Link>
        </section>
        <section className="card">
          <Store className="role-icon" aria-hidden="true" />
          <h2>Shop owner</h2>
          <p>Review the evidence and reply to the buyer.</p>
          <button className="button secondary" disabled>
            Shop inbox coming soon
          </button>
        </section>
      </div>
    </>
  );
}
