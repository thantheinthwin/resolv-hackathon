"use client";

import { ArrowLeft, ArrowRight, Plus, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { api, ApiError } from "../lib/client";
import type { Listing } from "../lib/models";
import { ListingOverview } from "./products";

const steps = ["Details", "Variants and box contents", "Photos and review"];
const entryFields = [
  ["colors", "Colors", "Add color", "Midnight black"],
  ["sizes", "Sizes or models", "Add size or model", "Medium"],
  ["box_contents", "Box contents", "Add box item", "Charging cable"],
] as const;
type EntryKey = (typeof entryFields)[number][0];
type Photo = { file: File; url: string };
type Entries = { items: string[]; input: string };
type Draft = {
  title: string;
  description: string;
  price: string;
  photos: Photo[];
} & Record<EntryKey, Entries>;

const emptyDraft: Draft = {
  title: "",
  description: "",
  price: "",
  colors: { items: [], input: "" },
  sizes: { items: [], input: "" },
  box_contents: { items: [], input: "" },
  photos: [],
};
const imageTypes = ["image/jpeg", "image/png", "image/webp"];

function commitEntry(entry: Entries): Entries {
  const value = entry.input.trim();
  return {
    items: value && !entry.items.includes(value) ? [...entry.items, value] : entry.items,
    input: "",
  };
}

export function ProductWizard({
  onCancel,
  onSaved,
  onDraftChange,
  onSaving,
}: {
  onCancel: () => void;
  onSaved: (item: Listing) => void;
  onDraftChange: (dirty: boolean) => void;
  onSaving: (saving: boolean) => void;
}) {
  const [draft, setDraft] = useState(emptyDraft);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [photoError, setPhotoError] = useState("");
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);
  const previewUrls = useRef(new Set<string>());
  const stepHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const urls = previewUrls.current;
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  function update(change: Partial<Draft>) {
    const next = { ...draft, ...change };
    setDraft(next);
    onDraftChange(
      Boolean(
        next.title ||
        next.description ||
        next.price ||
        next.photos.length ||
        entryFields.some(([key]) => next[key].input || next[key].items.length),
      ),
    );
    setError("");
  }

  function goTo(next: number) {
    setStep(next);
    setError("");
    requestAnimationFrame(() => stepHeading.current?.focus());
  }

  function choosePhotos(files: FileList) {
    const selected = Array.from(files);
    setPhotoError("");
    if (selected.length + draft.photos.length > 3) {
      setPhotoError("Choose up to three photos.");
      return;
    }
    if (selected.some((file) => !imageTypes.includes(file.type))) {
      setPhotoError("Choose JPEG, PNG, or WebP photos.");
      return;
    }
    const photos = selected.map((file) => {
      const url = URL.createObjectURL(file);
      previewUrls.current.add(url);
      return { file, url };
    });
    update({ photos: [...draft.photos, ...photos] });
  }

  function removePhoto(photo: Photo) {
    URL.revokeObjectURL(photo.url);
    previewUrls.current.delete(photo.url);
    setPhotoError("");
    update({ photos: draft.photos.filter((entry) => entry.url !== photo.url) });
  }

  function preview(): Omit<Listing, "id"> {
    return {
      title: draft.title.trim(),
      description: draft.description,
      price: Number(draft.price),
      photos: draft.photos.map(({ url }) => url),
      colors: draft.colors.items,
      sizes: draft.sizes.items,
      box_contents: draft.box_contents.items,
    };
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    if (step === 0) {
      if (!draft.title.trim()) {
        setError("Enter a product name.");
        return;
      }
      goTo(1);
      return;
    }
    if (step === 1) {
      update({
        colors: commitEntry(draft.colors),
        sizes: commitEntry(draft.sizes),
        box_contents: commitEntry(draft.box_contents),
      });
      goTo(2);
      return;
    }
    if (!draft.photos.length) {
      setPhotoError("Choose at least one product photo.");
      return;
    }

    const form = new FormData();
    form.set("title", draft.title.trim());
    form.set("description", draft.description);
    form.set("price", draft.price);
    for (const [key] of entryFields) {
      for (const item of draft[key].items) form.append(key, item);
    }
    for (const { file } of draft.photos) form.append("photos", file);

    inFlight.current = true;
    setSaving(true);
    onSaving(true);
    setError("");
    try {
      const listing = await api<Listing>("listings", form);
      onSaved(listing);
    } catch (error) {
      setError(
        error instanceof ApiError && error.status === 501
          ? "Product creation is available in the local demo."
          : error instanceof Error
            ? error.message
            : "Couldn’t save the product. Try again.",
      );
    } finally {
      inFlight.current = false;
      setSaving(false);
      onSaving(false);
    }
  }

  return (
    <div className="product-wizard">
      <ol className="report-steps" aria-label="Product setup progress">
        {steps.map((label, index) => (
          <li
            key={label}
            aria-current={index === step ? "step" : undefined}
            data-done={index < step}
          >
            <span aria-hidden="true">{index + 1}</span>
            {label}
          </li>
        ))}
      </ol>
      <h1 tabIndex={-1}>
        Add product<span className="heading-period">.</span>
      </h1>
      <form className="panel product-form" onSubmit={submit}>
        <h2 tabIndex={-1} ref={stepHeading}>
          {steps[step]}
        </h2>
        {step === 0 && (
          <>
            <div className="product-field">
              <label htmlFor="product-title">Product name</label>
              <Input
                id="product-title"
                required
                value={draft.title}
                onChange={(event) => update({ title: event.target.value })}
              />
            </div>
            <div className="product-field">
              <label htmlFor="product-description">
                Description <span className="muted-copy">(optional)</span>
              </label>
              <Textarea
                id="product-description"
                maxLength={1500}
                value={draft.description}
                onChange={(event) => update({ description: event.target.value })}
              />
            </div>
            <div className="product-field">
              <label htmlFor="product-price">Price</label>
              <Input
                id="product-price"
                type="number"
                min="0"
                step="any"
                required
                value={draft.price}
                onChange={(event) => update({ price: event.target.value })}
              />
            </div>
          </>
        )}
        {step === 1 &&
          entryFields.map(([key, label, action, placeholder]) => (
            <div className="product-field" key={key}>
              <label htmlFor={"product-" + key}>{label}</label>
              <div className="entry-input">
                <Input
                  id={"product-" + key}
                  placeholder={placeholder}
                  value={draft[key].input}
                  onChange={(event) =>
                    update({ [key]: { ...draft[key], input: event.target.value } })
                  }
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                      event.preventDefault();
                      update({ [key]: commitEntry(draft[key]) });
                    }
                  }}
                />
                <Button
                  type="button"
                  variant="outline"
                  disabled={!draft[key].input.trim()}
                  onClick={() => update({ [key]: commitEntry(draft[key]) })}
                >
                  <Plus aria-hidden /> {action}
                </Button>
              </div>
              {draft[key].items.length > 0 && (
                <ul className="entry-tags" aria-label={label + " added"}>
                  {draft[key].items.map((item) => (
                    <li key={item}>
                      <Button
                        type="button"
                        variant="secondary"
                        aria-label={"Remove " + item}
                        onClick={() =>
                          update({
                            [key]: {
                              ...draft[key],
                              items: draft[key].items.filter((entry) => entry !== item),
                            },
                          })
                        }
                      >
                        {item}
                        <X aria-hidden />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        {step === 2 && (
          <>
            <div className="product-field">
              <label htmlFor="product-photos">Product photos</label>
              <p id="product-photo-hint" className="muted-copy">
                Choose one to three photos. The first is the main image.
              </p>
              <Input
                id="product-photos"
                type="file"
                multiple
                accept={imageTypes.join(",")}
                aria-describedby={
                  photoError ? "product-photo-hint product-photo-error" : "product-photo-hint"
                }
                disabled={saving || draft.photos.length === 3}
                onChange={(event) => {
                  if (event.target.files?.length) choosePhotos(event.target.files);
                  event.target.value = "";
                }}
              />
            </div>
            {photoError && (
              <p id="product-photo-error" role="alert">
                {photoError}
              </p>
            )}
            {draft.photos.length > 0 && (
              <ul className="entry-tags" aria-label="Selected photos">
                {draft.photos.map((photo) => (
                  <li key={photo.url}>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={saving}
                      aria-label={"Remove " + photo.file.name}
                      onClick={() => removePhoto(photo)}
                    >
                      {photo.file.name}
                      <X aria-hidden />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <section className="product-preview" aria-label="Listing preview">
              <Badge variant="secondary">Listing preview</Badge>
              <h3>{draft.title.trim()}</h3>
              <ListingOverview listing={preview()} />
            </section>
          </>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="wizard-actions">
          <div className="action-row">
            {step > 0 && (
              <Button
                type="button"
                disabled={saving}
                variant="outline"
                onClick={() => goTo(step - 1)}
              >
                <ArrowLeft aria-hidden /> Back
              </Button>
            )}
            <Button type="button" disabled={saving} variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          </div>
          <Button disabled={saving}>
            {step < 2 ? "Continue" : saving ? "Saving product…" : "Save product"}
            <ArrowRight aria-hidden />
          </Button>
        </div>
      </form>
    </div>
  );
}
