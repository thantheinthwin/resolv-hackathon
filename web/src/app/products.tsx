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
import { Input } from "../components/ui/input";
import { Alert, AlertDescription } from "../components/ui/alert";
import { FormEvent, useState } from "react";
import { Listing } from "../lib/models";
import { api } from "../lib/client";
export function Products({ items, refresh }: { items: Listing[]; refresh: () => void }) {
  const [adding, add] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (f.getAll("photos").length > 3) {
      setError("Choose up to three photos.");
      return;
    }
    for (const key of ["colors", "sizes", "box_contents"]) {
      const list = String(f.get(key))
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      f.delete(key);
      list.forEach((v) => f.append(key, v));
    }
    setBusy(true);
    try {
      await api("listings", f);
      add(false);
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h1>Products.</h1>
      <Button onClick={() => add(!adding)}>{adding ? "Cancel" : "Add product"}</Button>
      {adding && (
        <form className="panel" onSubmit={submit}>
          {[
            ["title", "Product name"],
            ["description", "Description"],
            ["price", "Price"],
            ["colors", "Colours (comma separated)"],
            ["sizes", "Size or model (comma separated)"],
            ["box_contents", "Box contents (comma separated)"],
          ].map(([k, label]) => (
            <label key={k}>
              {label}
              <Input
                required={k === "title" || k === "price"}
                name={k}
                maxLength={k === "description" ? 1500 : undefined}
                type={k === "price" ? "number" : "text"}
                min="0"
                step="any"
              />
            </label>
          ))}
          <label>
            Product photos · first photo is main
            <Input
              required
              multiple
              name="photos"
              type="file"
              accept="image/jpeg,image/png,image/webp"
            />
          </label>
          <Button disabled={busy}>Save product</Button>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </form>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Product</TableHead>
            <TableHead>Colours</TableHead>
            <TableHead>Price</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((p) => (
            <TableRow key={p.id}>
              <TableCell>{p.title}</TableCell>
              <TableCell>{p.colors.join(", ")}</TableCell>
              <TableCell>{p.price}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}
