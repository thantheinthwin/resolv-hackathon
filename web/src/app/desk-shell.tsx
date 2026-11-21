"use client";

import { ArrowLeftRight, Gavel } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "../components/ui/button";

export function DeskShell({
  role,
  navigation,
  canLeave,
  navigationBlocked = false,
  view,
  children,
}: {
  role?: "Buyer" | "Shop owner";
  navigation?: ReactNode;
  canLeave?: () => boolean;
  navigationBlocked?: boolean;
  view: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const main = useRef<HTMLElement>(null);
  const previous = useRef(view);

  useEffect(() => {
    if (previous.current !== view) {
      const stepHeading = main.current?.querySelector<HTMLHeadingElement>("[data-step-heading]");
      if (stepHeading) {
        stepHeading.focus({ preventScroll: true });
        const bounds = stepHeading.getBoundingClientRect();
        if (bounds.top < 0 || bounds.bottom > window.innerHeight)
          stepHeading.scrollIntoView({ block: "nearest" });
      } else {
        (main.current?.querySelector("h1") ?? main.current)?.focus();
      }
      previous.current = view;
    }
  }, [view]);

  return (
    <div className="desktop">
      <a className="skip-link" href="#desk-content">
        Skip to content
      </a>
      <header className="desk-header">
        <Button
          variant="ghost"
          className="brand"
          disabled={navigationBlocked}
          onClick={() => {
            if (!canLeave || canLeave()) router.push("/");
          }}
        >
          <i>
            <Gavel size={23} aria-hidden />
          </i>
          Unboxing Judge
        </Button>
        {navigation && <nav aria-label={role + " navigation"}>{navigation}</nav>}
        {role && (
          <div className="desk-role-actions">
            <span className="desk-role">{role}</span>
            <Button asChild variant="outline" className="aria-disabled:opacity-50">
              {role === "Buyer" ? (
                <a
                  href="/shop"
                  aria-disabled={navigationBlocked || undefined}
                  title={navigationBlocked ? "Wait for your video upload to finish." : undefined}
                  onClick={(event) => {
                    if (navigationBlocked || (canLeave && !canLeave())) event.preventDefault();
                  }}
                >
                  <ArrowLeftRight aria-hidden /> Switch to shop owner
                </a>
              ) : (
                <Link
                  href="/orders"
                  onNavigate={(event) => {
                    if (canLeave && !canLeave()) event.preventDefault();
                  }}
                >
                  <ArrowLeftRight aria-hidden /> Switch to buyer
                </Link>
              )}
            </Button>
          </div>
        )}
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
