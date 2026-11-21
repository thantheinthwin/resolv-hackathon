"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Package, Store } from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardFooter } from "../components/ui/card";
import { BuyerDesk } from "./buyer-desk";
import { DeskShell } from "./desk-shell";
import { ShopDesk } from "./shop-desk";

export default function Desk({
  initialScreen = "roles",
}: {
  initialScreen?: "roles" | "orders" | "reports";
}) {
  const [shop, setShop] = useState(false);

  if (initialScreen !== "roles") return <BuyerDesk home={initialScreen} />;
  if (shop) return <ShopDesk onHome={() => setShop(false)} />;

  return (
    <DeskShell view="roles">
      <h1 tabIndex={-1}>
        Unboxing Judge<span className="heading-period">.</span>
      </h1>
      <div className="context role-options">
        <Card className="role-card">
          <CardContent>
            <Package aria-hidden />
            <h2>Buyer</h2>
            <p>Report a problem with a delivered order.</p>
          </CardContent>
          <CardFooter>
            <Button asChild>
              <Link href="/orders">
                Continue as buyer <ArrowRight aria-hidden />
              </Link>
            </Button>
          </CardFooter>
        </Card>
        <Card className="role-card">
          <CardContent>
            <Store aria-hidden />
            <h2>Shop owner</h2>
            <p>Review the evidence and reply to buyers.</p>
          </CardContent>
          <CardFooter>
            <Button variant="outline" onClick={() => setShop(true)}>
              Continue as shop owner <ArrowRight aria-hidden />
            </Button>
          </CardFooter>
        </Card>
      </div>
    </DeskShell>
  );
}
