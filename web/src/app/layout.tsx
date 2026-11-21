import type { Metadata } from "next";
import Header from "./header";
import "@fontsource/anuphan/400.css";
import "@fontsource/anuphan/600.css";
import "@fontsource/bricolage-grotesque/600.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./styles.css";

export const metadata: Metadata = { title: "Unboxing Judge" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="desktop">
          <Header />
          <main className="wrap">{children}</main>
          <footer>
            <div className="wrap">
              <span className="label">Unboxing Judge</span>
              <span>Evidence informs. People decide.</span>
            </div>
          </footer>
        </div>
        <p className="mobile">Open Unboxing Judge on a computer.</p>
      </body>
    </html>
  );
}
