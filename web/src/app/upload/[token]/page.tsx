"use client";
import { use, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Uploader } from "../../uploader";
export default function Phone({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params),
    [done, setDone] = useState(false),
    [warning, warn] = useState("");
  const order = useSearchParams().get("order");
  return (
    <main className="phone">
      <b>Unboxing Judge</b>
      <h1>{done ? "Done. You can close this page." : "Upload your unboxing video."}</h1>
      {order && <p>Order {order}</p>}
      {!done && (
        <Uploader
          getEndpoint={() => "uploads/" + encodeURIComponent(token)}
          onDone={({ warnings }) => {
            warn(warnings?.join(" ") ?? "");
            setDone(true);
          }}
        />
      )}
      {warning && <p>{warning}</p>}
    </main>
  );
}
