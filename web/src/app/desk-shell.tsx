"use client";

import { Gavel } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "../components/ui/button";

export function DeskShell({
  role,
  navigation,
  onHome,
  view,
  children,
}: {
  role?: "Buyer" | "Shop owner";
  navigation?: ReactNode;
  onHome?: () => void;
  view: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const main = useRef<HTMLElement>(null);
  const previous = useRef(view);

  useEffect(() => {
    if (previous.current !== view) {
      const heading = main.current?.querySelector("h1");
      (heading ?? main.current)?.focus();
      previous.current = view;
    }
  }, [view]);

  return (
    <div className="desktop">
      <a className="skip-link" href="#desk-content">
        Skip to content
      </a>
      <header className="desk-header">
        <Button variant="ghost" className="brand" onClick={onHome ?? (() => router.push("/"))}>
          <i>
            <Gavel size={23} aria-hidden />
          </i>
          Unboxing Judge
        </Button>
        {navigation && <nav aria-label={role + " navigation"}>{navigation}</nav>}
        {role && <span className="desk-role">{role}</span>}
      </header>
      <main id="desk-content" tabIndex={-1} ref={main}>
        {children}
      </main>
      <footer>
        <span>Unboxing Judge</span>
        <span>Evidence informs. People decide.</span>
      </footer>
    </div>
  );
}
