"use client";

import Link from "next/link";
import { Package } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { api } from "../lib/client";
import type { Listing } from "../lib/models";
import { parseProductLink, productPath } from "../lib/product-links";

export function ProductReference({ listing }: { listing: Listing }) {
  return (
    <>
      {listing.photos[0] ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="order-photo" src={listing.photos[0]} alt="" />
      ) : (
        <span className="order-photo order-icon">
          <Package aria-hidden />
        </span>
      )}
      <span className="product-reference">
        <strong>{listing.title}</strong>
        <span className="muted-copy">{[...listing.colors, ...listing.sizes].join(" · ")}</span>
        <small>฿{listing.price.toLocaleString()}</small>
      </span>
    </>
  );
}

export function ClaimProduct({
  linkedProduct,
  busy,
  onConfirm,
}: {
  linkedProduct?: string;
  busy: boolean;
  onConfirm: (listing: Listing) => void;
}) {
  const [listings, setListings] = useState<Listing[]>();
  const [loadError, setLoadError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [input, setInput] = useState<string>();
  const [checked, setChecked] = useState<string>();
  const [origin, setOrigin] = useState("");
  useEffect(() => {
    let active = true;
    api<Listing[]>("listings").then(
      (items) => {
        if (active) {
          setListings(items);
          setOrigin(location.origin);
        }
      },
      () => {
        if (active) setLoadError(true);
      },
    );
    return () => {
      active = false;
    };
  }, [retry]);
  const prefilled = linkedProduct && origin ? origin + productPath(linkedProduct) : "";
  const value = input ?? prefilled;
  const candidate = checked ?? (input === undefined ? prefilled : "");
  const result = candidate ? parseProductLink(candidate, origin) : undefined;
  const item = result && "id" in result ? listings?.find((row) => row.id === result.id) : undefined;
  const error =
    result && "error" in result
      ? result.error
      : result && listings && !item
        ? "We couldn’t find that item. Check the link or browse the products."
        : "";
  return (
    <div className="claim-product">
      <Link className="text-link" href="/products">
        Browse products
      </Link>
      <form
        className="claim-search"
        onSubmit={(event) => {
          event.preventDefault();
          setChecked(value);
        }}
      >
        <label htmlFor="product-link">Product link</label>
        <Input
          id="product-link"
          type="text"
          inputMode="url"
          required
          value={value}
          onChange={(event) => {
            setInput(event.target.value);
            setChecked(undefined);
          }}
          aria-describedby="link-help"
        />
        <p id="link-help">Already have a product link? Paste it here.</p>
        <Button type="submit" disabled={busy}>
          Find my item
        </Button>
      </form>
      {error && <p role="alert">{error}</p>}
      {loadError && (
        <p role="status">
          Couldn’t load the shop’s items.{" "}
          <Button
            onClick={() => {
              setLoadError(false);
              setRetry((n) => n + 1);
            }}
          >
            Try again
          </Button>
        </p>
      )}
      {candidate && !listings && !loadError && <p role="status">Finding your item…</p>}
      {item && (
        <div className="claim-product-match">
          <h3>Is this your item?</h3>
          <div className="order-context">
            <ProductReference listing={item} />
          </div>
          <Button disabled={busy} onClick={() => onConfirm(item)}>
            Yes, this is my item
          </Button>
        </div>
      )}
    </div>
  );
}
