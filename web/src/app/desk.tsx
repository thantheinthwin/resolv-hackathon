"use client";
import { Button } from "../components/ui/button";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableCell,
  TableHead,
} from "../components/ui/table";
import { Textarea } from "../components/ui/textarea";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Card, CardContent, CardFooter } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { RadioGroup, RadioGroupItem } from "../components/ui/radio-group";
import { Gavel, Package, Store, ArrowRight } from "lucide-react";
import { useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import QRCode from "qrcode";
import { api } from "../lib/client";
import {
  Case,
  CreatedCase,
  InboxCase,
  Order,
  Report,
  Listing,
  claims,
  labels,
} from "../lib/models";
import { Products } from "./products";
import { Review } from "./review";
import { CheckProgress } from "./check-progress";
import { Uploader } from "./uploader";
export default function Desk({ initialScreen = "roles" }: { initialScreen?: string }) {
  const router = useRouter(),
    pathname = usePathname();
  const [screen, go] = useState(initialScreen),
    [orders, setOrders] = useState<Order[]>([]),
    [order, select] = useState<Order>(),
    [claim, choose] = useState<keyof typeof claims>("wrong_item"),
    [description, describe] = useState(""),
    [id, setId] = useState(""),
    [reports, setReports] = useState<Report[]>([]),
    [cases, setCases] = useState<InboxCase[]>([]),
    [current, open] = useState<Case>(),
    [products, setProducts] = useState<Listing[]>([]),
    [error, fail] = useState(""),
    [message, say] = useState(""),
    [qr, setQR] = useState(""),
    [url, setUrl] = useState(""),
    [rev, refresh] = useState(0),
    [busy, wait] = useState(false);
  const shop = ["inbox", "case", "products"].includes(screen);
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        if (screen === "orders") {
          const v = await api<Order[]>("orders");
          if (active) setOrders(v);
        }
        if (screen === "reports") {
          const v = await api<Report[]>("my/cases");
          if (active) setReports(v);
        }
        if (screen === "inbox") {
          const v = await api<InboxCase[]>("shop/cases");
          if (active)
            setCases(
              v.sort(
                (a, b) =>
                  Number(b.display === "unsure") - Number(a.display === "unsure") ||
                  b.created_at.localeCompare(a.created_at),
              ),
            );
        }
        if (screen === "products") {
          const v = await api<Listing[]>("listings");
          if (active) setProducts(v);
        }
        if (screen === "video" && url) {
          const v = await api<Report>("cases/" + id);
          if (active && v.status === "failed") {
            say("The video was received, but checking failed.");
            go("reports");
          } else if (active && ["checking", "with_shop", "replied"].includes(v.status)) go("sent");
        }
      } catch (e) {
        if (active) fail(String(e));
      }
    }
    load();
    const timer = ["reports", "inbox", "video"].includes(screen)
      ? setInterval(load, 2000)
      : undefined;
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [screen, rev, url, id]);
  useEffect(() => {
    if (screen !== "video" || !url) return;
    const events = new EventSource("/api/cases/" + id + "/events");
    const update = () => refresh((v) => v + 1);
    events.onmessage = update;
    events.addEventListener("done", update);
    return () => events.close();
  }, [screen, url, id]);
  function nav(s: string) {
    if (s === "reports" && pathname !== "/reports") {
      router.push("/reports");
      return;
    }
    fail("");
    say("");
    if (s === "orders" && pathname !== "/orders") {
      router.push("/orders");
      return;
    }
    if (s === "roles" && pathname !== "/") {
      router.push("/");
      return;
    }
    go(s);
  }
  async function act(fn: () => Promise<void>) {
    if (busy) return;
    wait(true);
    fail("");
    try {
      await fn();
    } catch (e) {
      fail(String(e));
    } finally {
      wait(false);
    }
  }
  return (
    <>
      <div className="desktop">
        <header>
          <Button variant="ghost" className="brand" onClick={() => nav("roles")}>
            <i>
              <Gavel size={23} aria-hidden />
            </i>{" "}
            Unboxing Judge
          </Button>
          <nav>
            {(shop
              ? [
                  ["inbox", "Inbox"],
                  ["products", "Products"],
                ]
              : screen === "roles"
                ? []
                : [
                    ["orders", "Your orders"],
                    ["reports", "My reports"],
                  ]
            ).map(([s, n]) => (
              <Button variant="outline" className="quiet" key={s} onClick={() => nav(s)}>
                {n}
              </Button>
            ))}
          </nav>
          <small>{screen === "roles" ? "Review desk" : shop ? "Shop owner" : "Buyer"}</small>
        </header>
        <main>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {message && <p role="status">{message}</p>}
          {screen === "roles" ? (
            <>
              <h1>Unboxing Judge.</h1>
              <p>Choose your role.</p>
              <div className="context">
                {[
                  ["orders", "Buyer", "Report a problem with a delivered order."],
                  ["inbox", "Shop owner", "Review the evidence and reply to buyers."],
                ].map(([s, n, d]) => (
                  <Card key={s} className="role-card">
                    <CardContent>
                      {s === "orders" ? <Package aria-hidden /> : <Store aria-hidden />}
                      <h2>{n}</h2>
                      <p>{d}</p>
                    </CardContent>
                    <CardFooter>
                      <Button
                        variant={s === "orders" ? "default" : "outline"}
                        onClick={() => nav(s)}
                      >
                        Continue as {n.toLowerCase()}
                        <ArrowRight aria-hidden />
                      </Button>
                    </CardFooter>
                  </Card>
                ))}
              </div>
            </>
          ) : shop ? (
            <>
              {screen === "products" ? (
                <Products items={products} refresh={() => refresh(rev + 1)} />
              ) : screen === "case" && current ? (
                <Review
                  item={current}
                  reload={async () => open(await api<Case>("shop/cases/" + current.id))}
                  title={
                    cases.find((item) => item.id === current.id)?.product || "Product unavailable"
                  }
                  saved={() => {
                    go("inbox");
                    say("Decision saved");
                  }}
                />
              ) : (
                <>
                  <h1>Inbox.</h1>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Order</TableHead>
                        <TableHead>Claim</TableHead>
                        <TableHead>Review</TableHead>
                        <TableHead>Confidence</TableHead>
                        <TableHead>Received</TableHead>
                        <TableHead></TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {cases.map((c) => (
                        <TableRow key={c.id} data-case={c.id}>
                          <TableCell>
                            {typeof c.product === "string" && <strong>{c.product}</strong>}
                            {c.order_id}
                          </TableCell>
                          <TableCell>{claims[c.claim_type as keyof typeof claims]}</TableCell>
                          <TableCell>
                            {c.status === "checking" ? (
                              <CheckProgress id={c.id} onDone={() => refresh((v) => v + 1)} />
                            ) : (
                              <>
                                <span>
                                  {c.verdict === "buyer_right"
                                    ? "Buyer is right"
                                    : c.verdict === "seller_right"
                                      ? "Seller is right"
                                      : c.verdict === "needs_human"
                                        ? "Needs human review"
                                        : ""}
                                </span>{" "}
                                <Badge variant="outline">{c.display || labels[c.status]}</Badge>
                              </>
                            )}
                          </TableCell>
                          <TableCell>
                            {c.confidence != null ? Math.round(c.confidence * 100) + "%" : "—"}
                          </TableCell>
                          <TableCell>{new Date(c.created_at).toLocaleTimeString()}</TableCell>
                          <TableCell>
                            <Button
                              disabled={busy || !["ready", "decided"].includes(c.status)}
                              onClick={() =>
                                act(async () => {
                                  open(await api<Case>("shop/cases/" + c.id));
                                  nav("case");
                                })
                              }
                            >
                              Review case
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {!cases.length && <p>No cases yet.</p>}
                </>
              )}
            </>
          ) : (
            <div className="buyer">
              <article>
                {screen === "orders" && (
                  <>
                    <h1>Your orders.</h1>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Delivered order</TableHead>
                          <TableHead>Variant</TableHead>
                          <TableHead>Quantity</TableHead>
                          <TableHead></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {orders.map((o) => (
                          <TableRow key={o.id}>
                            <TableCell>
                              <strong>{o.listing.title}</strong>
                              <small>{o.id}</small>
                            </TableCell>
                            <TableCell>
                              {o.variant.color} · {o.variant.size}
                            </TableCell>
                            <TableCell>{o.quantity}</TableCell>
                            <TableCell>
                              <Button
                                onClick={() => {
                                  select(o);
                                  setId("");
                                  describe("");
                                  choose("wrong_item");
                                  setUrl("");
                                  setQR("");
                                  nav("complaint");
                                }}
                              >
                                Report a problem
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </>
                )}
                {["complaint", "video", "sent"].includes(screen) && (
                  <small>The order　 /　 The video　 /　 Sent</small>
                )}
                {screen === "complaint" && (
                  <>
                    <h1>Tell us what went wrong.</h1>
                    <p>
                      {order?.listing.title} · {order?.variant.color} · Qty {order?.quantity}
                    </p>
                    <RadioGroup
                      aria-label="Claim type"
                      className="choices"
                      value={claim}
                      onValueChange={(value) => choose(value as keyof typeof claims)}
                    >
                      {Object.entries(claims).map(([key, label]) => (
                        <label className="claim-option" key={key}>
                          <RadioGroupItem value={key} />
                          {label}
                        </label>
                      ))}
                    </RadioGroup>
                    <label>
                      What happened? (optional)
                      <Textarea value={description} onChange={(e) => describe(e.target.value)} />
                    </label>
                    <Button
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          const c = await api<CreatedCase>("cases", {
                            order_id: order?.id,
                            claim_type: claim,
                            description,
                          });
                          setId(c.id);
                          nav("video");
                        })
                      }
                    >
                      Continue to video
                    </Button>
                  </>
                )}
                {screen === "video" && (
                  <>
                    <h1>The video.</h1>
                    <Uploader
                      endpoint={"cases/" + id + "/video"}
                      onDone={(w) => {
                        nav("sent");
                        say(w);
                      }}
                    />
                    <Button
                      className="quiet"
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          const r = await api<{ token: string; url: string }>(
                            "cases/" + id + "/upload-link",
                            {},
                          );
                          const publicOrigin =
                            process.env.NEXT_PUBLIC_WEB_ORIGIN || location.origin;
                          const target = new URL(
                            r.url || "/upload/" + encodeURIComponent(r.token),
                            publicOrigin,
                          );
                          if (process.env.NEXT_PUBLIC_WEB_ORIGIN) {
                            const configured = new URL(publicOrigin);
                            target.protocol = configured.protocol;
                            target.host = configured.host;
                          }
                          target.searchParams.set("order", order?.id || "");
                          const link = target.href;
                          setQR(await QRCode.toDataURL(link));
                          setUrl(link);
                        })
                      }
                    >
                      Upload from phone
                    </Button>
                    {qr && (
                      <div>
                        <img src={qr} alt="Scan to upload from your phone" />
                        <a href={url}>Open phone upload</a>
                      </div>
                    )}
                  </>
                )}
                {screen === "sent" && (
                  <>
                    <h1>Sent to the shop.</h1>
                    <Button onClick={() => nav("reports")}>View my reports</Button>
                  </>
                )}
                {screen === "reports" && (
                  <>
                    <h1>My reports.</h1>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Report</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Shop note</TableHead>
                          <TableHead>Actions</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {reports.map((r) => (
                          <TableRow key={r.id}>
                            <TableCell>{r.id.slice(0, 8)}</TableCell>
                            <TableCell>
                              <Badge variant="secondary">{labels[r.status] || r.status}</Badge>
                            </TableCell>
                            <TableCell>{r.note_for_buyer || "—"}</TableCell>
                            <TableCell>
                              <Button
                                variant="outline"
                                disabled={busy}
                                onClick={() => {
                                  if (
                                    window.confirm(
                                      "Delete this report, video and evidence permanently?",
                                    )
                                  )
                                    act(async () => {
                                      await api("cases/" + r.id, undefined, "DELETE");
                                      setReports((items) =>
                                        items.filter((item) => item.id !== r.id),
                                      );
                                      refresh((v) => v + 1);
                                      say("Report deleted");
                                    });
                                }}
                              >
                                Delete report
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </>
                )}
              </article>
              <aside className="panel desk">
                <small>The review desk</small>
                <h2>What happens next.</h2>
                <p>The shop reviews your video alongside your order and replies in My reports.</p>
                <hr />
                <p>
                  Film the parcel and the item. Keep faces and personal details out of the frame.
                </p>
              </aside>
            </div>
          )}
        </main>
        <footer>
          Unboxing Judge <span>Evidence informs. People decide.</span>
        </footer>
      </div>
    </>
  );
}
