"use client";

import { Package, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { api } from "../lib/client";
import type { Listing } from "../lib/models";
import { suggestProducts } from "../lib/product-search";

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
        <small>Product reference {listing.id.slice(0, 8)}</small>
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
  const [query, setQuery] = useState("");
  const [suggestionId, setSuggestionId] = useState<string>();
  const input = useRef<HTMLInputElement>(null);
  const results = useRef<HTMLUListElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let active = true;
    api<Listing[]>("listings").then(
      (items) => {
        if (active) setListings(items);
      },
      () => {
        if (active) setLoadError(true);
      },
    );
    return () => {
      active = false;
    };
  }, [retry]);

  const value = query.trim();
  const looksLikeLink = /^(?:[a-z][\w+.-]*:\/\/|www\.)/i.test(value);
  const linkId = looksLikeLink ? claimLinkId(value) : undefined;
  const selectedId = value ? (linkId ?? suggestionId) : linkedProduct;
  const selected = listings?.find((item) => item.id === selectedId);
  const matches = useMemo(
    () =>
      listings && value && !looksLikeLink && !suggestionId
        ? suggestProducts(listings, value)
        : undefined,
    [listings, looksLikeLink, suggestionId, value],
  );
  const inputMessage =
    looksLikeLink && !linkId
      ? "Use a claim link from this app or type the product name."
      : selectedId !== undefined && listings && !selected
        ? "This product is unavailable. Try searching by name."
        : matches?.length === 0
          ? "No matching products. Try a name, color, or reference."
          : "";

  function selectSuggestion(listing: Listing) {
    setSuggestionId(listing.id);
    requestAnimationFrame(() => confirm.current?.focus());
  }

  return (
    <div className="claim-product">
      <div className="claim-search">
        <label htmlFor="product-search">Find your product</label>
        <div className="claim-search-field">
          <Search size={16} aria-hidden />
          <Input
            id="product-search"
            ref={input}
            type="search"
            placeholder="Search by name or paste a claim link"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setSuggestionId(undefined);
            }}
            onKeyDown={(event) => {
              if (busy || event.nativeEvent.isComposing) return;
              if (event.key === "ArrowDown" && matches?.length) {
                event.preventDefault();
                results.current?.querySelector("button")?.focus();
              }
              if (event.key === "Enter" && matches?.[0]) {
                event.preventDefault();
                selectSuggestion(matches[0]);
              } else if (event.key === "Enter" && selected) {
                event.preventDefault();
                confirm.current?.focus();
              }
            }}
            aria-controls={matches?.length ? "product-suggestions" : undefined}
            aria-describedby={inputMessage ? "product-search-message" : undefined}
            autoComplete="off"
          />
        </div>
        {inputMessage && (
          <p className="muted-copy" id="product-search-message" role="status">
            {inputMessage}
          </p>
        )}
        {!!matches?.length && (
          <ul
            className="claim-search-results"
            id="product-suggestions"
            aria-label="Matching products"
            ref={results}
            onKeyDown={(event) => {
              if (event.key === "Escape") input.current?.focus();
              if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
              const buttons = [...event.currentTarget.querySelectorAll("button")];
              const index = buttons.findIndex((button) => button === document.activeElement);
              const next = buttons[index + (event.key === "ArrowDown" ? 1 : -1)];
              event.preventDefault();
              if (next) next.focus();
              else if (event.key === "ArrowUp") input.current?.focus();
            }}
          >
            {matches.map((listing) => (
              <li key={listing.id}>
                <button
                  type="button"
                  className="order-context"
                  disabled={busy}
                  onClick={() => selectSuggestion(listing)}
                >
                  <ProductReference listing={listing} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {loadError ? (
        <div className="action-row" role="status">
          Couldn’t load the inventory.
          <Button
            variant="outline"
            onClick={() => {
              setLoadError(false);
              setRetry((value) => value + 1);
            }}
          >
            Try again
          </Button>
        </div>
      ) : (
        !listings && (
          <p className="muted-copy" role="status">
            Loading products…
          </p>
        )
      )}
      {selected && (
        <div className="claim-product-match" aria-label="Product to confirm" role="group">
          <div className="order-context">
            <ProductReference listing={selected} />
          </div>
          {selected.box_contents.length > 0 && (
            <p>
              <strong>Box contents</strong> · {selected.box_contents.join(", ")}
            </p>
          )}
          <Button ref={confirm} disabled={busy} onClick={() => onConfirm(selected)}>
            Confirm product
          </Button>
        </div>
      )}
    </div>
  );
}

function claimLinkId(value: string) {
  try {
    const url = new URL(value);
    const configured = process.env.NEXT_PUBLIC_WEB_ORIGIN;
    const sameApp =
      url.origin === location.origin || (configured && url.origin === new URL(configured).origin);
    const [id, ...extra] = url.searchParams.getAll("product");
    return sameApp && url.pathname === "/orders" && id && extra.length === 0 ? id : undefined;
  } catch {
    return undefined;
  }
}
