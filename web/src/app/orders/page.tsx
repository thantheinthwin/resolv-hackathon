import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import type { paths } from "../../api/types";

type Orders = paths["/api/orders"]["get"]["responses"][200]["content"]["application/json"];

export const dynamic = "force-dynamic";

async function loadOrders(): Promise<Orders | null> {
  const passcode = process.env.DEMO_PASSCODE;
  if (!passcode) return null;
  try {
    const response = await fetch(
      new URL("/api/orders", process.env.API_BASE_URL || "http://127.0.0.1:8000"),
      {
        headers: { "X-Demo-Passcode": passcode },
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    if (response.ok) return await response.json();
  } catch {
    // The buyer can retry when the local Case API is available.
  }
  return null;
}

export default async function OrdersPage() {
  const orders = await loadOrders();
  return (
    <>
      <Link href="/" className="back">
        <ArrowLeft size={16} aria-hidden="true" /> Switch role
      </Link>
      <h1>
        Your orders<span>.</span>
      </h1>
      <div className="buyer-layout">
        <section className="table-panel" aria-label="Delivered orders">
          {orders === null ? (
            <div className="empty" role="alert">
              Your orders could not be loaded. <a href="/orders">Try again</a>
            </div>
          ) : orders.length === 0 ? (
            <p className="empty">You have no delivered orders.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">Product and order</th>
                  <th scope="col">Variant</th>
                  <th scope="col">Qty</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr key={order.id}>
                    <td>
                      <strong>{order.listing.title}</strong>
                      <small>{order.id}</small>
                    </td>
                    <td>
                      {[order.variant.color, order.variant.size].filter(Boolean).join(" · ") || "—"}
                    </td>
                    <td>{order.quantity}</td>
                    <td>
                      <button className="button outline" disabled aria-describedby="report-status">
                        Report a problem
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {orders && orders.length > 0 && (
            <p className="availability" id="report-status">
              Complaint submission is coming soon.
            </p>
          )}
        </section>
        <aside className="desk">
          <span className="label">The review desk</span>
          <h2>
            What happens next<span>?</span>
          </h2>
          <p>
            Share your complaint and an unboxing video. The shop reviews the evidence and replies to
            your report.
          </p>
          <div className="privacy">
            <ShieldCheck size={20} aria-hidden="true" />
            <p>You can see the status of your report and the shop’s note.</p>
          </div>
        </aside>
      </div>
    </>
  );
}
