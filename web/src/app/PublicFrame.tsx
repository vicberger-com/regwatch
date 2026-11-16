import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, type ReactNode } from "react";

import { COLOR, publicBrandingQuery } from "@/features/branding/api";

/**
 * The frame of pages anyone may open (sign-in, legal): the public branding (CP-08) with the
 * screen name in the title, the accent colour, and a `main` landmark.
 */
export function PublicFrame({
  screen,
  children,
}: {
  screen: string;
  children: ReactNode;
}) {
  const branding = useQuery(publicBrandingQuery);
  const title = branding.data?.site_title || "regwatch";
  const color = branding.data?.primary_color;

  useEffect(() => {
    document.title = `${screen} · ${title}`;
  }, [screen, title]);
  useEffect(() => {
    const root = document.documentElement.style;
    if (color && COLOR.test(color)) root.setProperty("--brand-accent", color);
    else root.removeProperty("--brand-accent");
  }, [color]);

  return (
    <div className="flex min-h-screen flex-col items-center bg-bg px-4 text-text">
      <header className="mt-12 flex items-center gap-3">
        {branding.data?.logo_url && (
          <img src={branding.data.logo_url} alt="" className="h-12 w-auto" />
        )}
        <span className="text-xl font-semibold">{title}</span>
      </header>
      <main id="main" className="mt-6 w-full max-w-3xl">
        {children}
      </main>
      <footer className="my-6 text-sm text-text-muted">
        {branding.data?.has_legal_page && screen !== "Legal" && (
          <Link to="/legal">Legal</Link>
        )}
        {screen === "Legal" && <Link to="/">Back to {title}</Link>}
      </footer>
    </div>
  );
}
