import type { Listing } from "./models";

const synonyms: Record<string, string> = {
  tee: "shirt",
  tshirt: "shirt",
  shirts: "shirt",
  trousers: "pants",
  trainers: "sneakers",
  earbuds: "earphones",
  grey: "gray",
  colour: "color",
  small: "s",
  medium: "m",
  large: "l",
};
const ignored = new Set(["a", "an", "the", "in", "for", "with", "and", "size", "color"]);
const words = new Intl.Segmenter("en", { granularity: "word" });

function normalize(value: string) {
  return value.normalize("NFKC").trim().toLowerCase().replace(/\s+/g, " ");
}

function terms(value: string) {
  const normalized = normalize(value).replace(/\bt[\s-]+shirts?\b/g, "shirt");
  return [...words.segment(normalized)]
    .filter(({ isWordLike }) => isWordLike)
    .map(({ segment }) => (Object.hasOwn(synonyms, segment) ? synonyms[segment] : segment));
}

function oneTypo(a: string, b: string) {
  if (!/^[a-z]+$/.test(a) || a.length < 4 || Math.abs(a.length - b.length) > 1) return false;
  const index = [...a].findIndex((character, offset) => character !== b[offset]);
  if (index === -1) return b.length === a.length + 1;
  if (a.length < b.length) return a.slice(index) === b.slice(index + 1);
  if (a.length > b.length) return a.slice(index + 1) === b.slice(index);
  return (
    a.slice(index + 1) === b.slice(index + 1) ||
    (a[index] === b[index + 1] &&
      a[index + 1] === b[index] &&
      a.slice(index + 2) === b.slice(index + 2))
  );
}

function matchTerm(query: string, candidates: string[]) {
  if (candidates.includes(query)) return 4;
  if (query.length >= 2 && candidates.some((word) => word.startsWith(query))) return 3;
  return candidates.some((word) => oneTypo(query, word)) ? 1 : 0;
}

export function suggestProducts(listings: Listing[], input: string): Listing[] {
  const normalized = normalize(input);
  const exactReference = listings.filter(({ id }) =>
    [id.toLowerCase(), id.slice(0, 8).toLowerCase()].includes(normalized),
  );
  if (exactReference.length) return exactReference;

  const query = [...new Set(terms(normalized).filter((word) => !ignored.has(word)))];
  if (!query.length) return [];
  return listings
    .flatMap((listing) => {
      const title = normalize(listing.title);
      const titleTerms = terms(title);
      const details = terms(
        [listing.description, ...listing.colors, ...listing.sizes, ...listing.box_contents].join(
          " ",
        ),
      );
      const scores = query.map((word) =>
        Math.max(matchTerm(word, titleTerms) * 2, matchTerm(word, details)),
      );
      const coverage = scores.filter(Boolean).length;
      if (coverage < Math.ceil(query.length / 2)) return [];
      return [
        {
          listing,
          exactTitle: Number(title === normalized),
          coverage,
          score: scores.reduce((sum, value) => sum + value, 0),
        },
      ];
    })
    .sort((a, b) => b.exactTitle - a.exactTitle || b.coverage - a.coverage || b.score - a.score)
    .slice(0, 6)
    .map(({ listing }) => listing);
}
