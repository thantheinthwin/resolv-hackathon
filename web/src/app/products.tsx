"use client";

import { ArrowRight, Link as LinkIcon, Plus } from "lucide-react";
import { useState } from "react";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { productPath, publicProductOrigin } from "../lib/product-links";
import type { Listing } from "../lib/models";

type ListingOverviewFields = Omit<Listing, "id">;

function formatPrice(price: number) {
  return price.toLocaleString(undefined, { maximumFractionDigits: 20 });
}

export function ProductLink({ id }: { id: string }) {
  const [state, setState] = useState<{ url: string; copied: boolean }>();

  async function copyLink() {
    const url = new URL(productPath(id), publicProductOrigin(location.origin));
    try {
      await navigator.clipboard.writeText(url.href);
      setState({ url: url.href, copied: true });
    } catch {
      setState({ url: url.href, copied: false });
    }
  }

  return (
    <div className="product-claim-link">
      <Button variant="outline" onClick={() => void copyLink()}>
        <LinkIcon aria-hidden /> Copy product link
      </Button>
      {state?.copied && <span role="status">Product link copied.</span>}
      {state && !state.copied && (
        <label className="claim-link-fallback">
          Product link
          <Input type="url" readOnly value={state.url} onFocus={(event) => event.target.select()} />
        </label>
      )}
    </div>
  );
}

export function Products({
  items,
  loading,
  onAdd,
  onOpen,
}: {
  items: Listing[];
  loading: boolean;
  onAdd: () => void;
  onOpen: (item: Listing) => void;
}) {
  return (
    <>
      <div className="product-heading">
        <h1 tabIndex={-1}>
          Products<span className="heading-period">.</span>
        </h1>
        <Button onClick={onAdd}>
          <Plus aria-hidden /> Add product
        </Button>
      </div>
      {loading && (
        <p className="loading-row" role="status">
          Loading products…
        </p>
      )}
      {!loading && items.length === 0 && (
        <p className="empty-state">Add a product to start your catalogue.</p>
      )}
      {items.length > 0 && (
        <ul className="product-list" aria-label="Products">
          {items.map((item) => (
            <li key={item.id}>
              <button className="product-row" type="button" onClick={() => onOpen(item)}>
                {/* The demo serves listing images through its own API. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img className="order-photo" src={item.photos[0]} alt="" />
                <span className="product-row-text">
                  <strong>{item.title}</strong>
                  {item.colors.length > 0 && (
                    <span className="muted-copy">{item.colors.join(", ")}</span>
                  )}
                </span>
                <span className="product-price">{formatPrice(item.price)}</span>
                <ArrowRight aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function ListingOverview({ listing }: { listing: ListingOverviewFields }) {
  return (
    <div className="listing-overview">
      {listing.photos.length > 0 && (
        <ul className="listing-photos" aria-label="Product photos">
          {listing.photos.map((photo, index) => (
            <li key={photo + index}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={photo} alt={listing.title + ", photo " + (index + 1)} />
              {index === 0 && <Badge variant="secondary">Main image</Badge>}
            </li>
          ))}
        </ul>
      )}
      <dl className="listing-fields">
        <div>
          <dt>Price</dt>
          <dd className="product-price">{formatPrice(listing.price)}</dd>
        </div>
        {listing.description && (
          <div>
            <dt>Description</dt>
            <dd>{listing.description}</dd>
          </div>
        )}
        {(
          [
            ["Colors", listing.colors],
            ["Sizes or models", listing.sizes],
            ["Box contents", listing.box_contents],
          ] as const
        ).map(([label, entries]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              {entries.length ? (
                entries.join(", ")
              ) : (
                <span className="muted-copy">None listed</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
