import "@fontsource/anuphan/400.css";
import "@fontsource/anuphan/600.css";
import "@fontsource/bricolage-grotesque/600.css";
import "@fontsource/ibm-plex-mono/500.css";
import type { ReactNode } from "react";
import "./style.css";
export const metadata = { title: "Unboxing Judge · Review desk" };
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
