"use client";

import Link from "next/link";
import { ArrowRight, Package, Store } from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardFooter } from "../components/ui/card";
import { DeskShell } from "./desk-shell";

export default function Desk() {
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
            <p>Find an item, report a problem, or check a report.</p>
          </CardContent>
          <CardFooter>
            <Link className="text-link" href="/products">
              Browse products
            </Link>
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
            <Button asChild variant="outline">
              <a href="/shop">
                Continue as shop owner <ArrowRight aria-hidden />
              </a>
            </Button>
          </CardFooter>
        </Card>
      </div>
    </DeskShell>
  );
}
