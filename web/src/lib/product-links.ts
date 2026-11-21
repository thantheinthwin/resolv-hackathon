export function productPath(id: string) {
  return "/products/" + encodeURIComponent(id);
}

export function publicProductOrigin(current: string) {
  const configured = URL.parse(process.env.NEXT_PUBLIC_WEB_ORIGIN || "");
  return configured && ["http:", "https:"].includes(configured.protocol)
    ? configured.origin
    : current;
}

export function shopProductPath(id: string) {
  return "/shop" + productPath(id);
}

export function parseProductLink(
  input: string,
  origin: string,
): { id: string } | { error: string } {
  try {
    const url = new URL(input.trim());
    if (
      (url.origin === origin || url.origin === publicProductOrigin(origin)) &&
      !url.username &&
      !url.password
    ) {
      if (url.pathname.startsWith("/shop/")) {
        return {
          error:
            "That link opens the shop owner’s view. Ask the shop for the link they share with shoppers.",
        };
      }
      const match = /^\/products\/([\w-]+)\/?$/.exec(url.pathname);
      if (match) return { id: match[1] };
    }
  } catch {
    // A pasted link may be incomplete.
  }
  return { error: "Open the item’s page in this shop, then copy and paste its link here." };
}
