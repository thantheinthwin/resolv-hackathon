"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Gavel } from "lucide-react";

export default function Header() {
  const isBuyer = usePathname() === "/orders";
  return (
    <header>
      <div className="wrap">
        <Link href="/" className="brand" aria-label="Unboxing Judge, choose a role">
          <span className="mark">
            <Gavel aria-hidden="true" />
          </span>
          Unboxing Judge
        </Link>
        <span className="caption">{isBuyer ? "Your orders" : "Unboxing review"}</span>
        <span className="role-pill">{isBuyer ? "Buyer" : "Choose a role"}</span>
      </div>
    </header>
  );
}
