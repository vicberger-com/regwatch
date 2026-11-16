import { useQuery } from "@tanstack/react-query";
import { Link, useMatches } from "@tanstack/react-router";
import { useEffect } from "react";

import { brandingQuery, COLOR } from "@/features/branding/api";
import { api } from "@/lib/api/client";

const versionQuery = {
  queryKey: ["version"],
  queryFn: async () => {
    const result = await api.GET("/version");
    return result.response.ok ? (result.data ?? null) : null;
  },
  staleTime: Infinity,
};

/** The header brand: logo and site title (screens.md), with the page title to match. */
export function BrandMark() {
  const branding = useQuery(brandingQuery);
  const title = branding.data?.site_title || "regwatch";
  const color = branding.data?.primary_color;
  // "<Screen> · <site title>", from the deepest route that names its screen (use testing U-M0-4).
  const screen = useMatches()
    .map((m) => m.staticData.title)
    .filter(Boolean)
    .at(-1);

  useEffect(() => {
    document.title = screen ? `${screen} · ${title}` : title;
  }, [screen, title]);
  useEffect(() => {
    // Only a checked hex value ever reaches the style; the API enforces the same pattern.
    const root = document.documentElement.style;
    if (color && COLOR.test(color)) root.setProperty("--brand-accent", color);
    else root.removeProperty("--brand-accent");
  }, [color]);

  return (
    <Link to="/" className="flex items-center gap-2 text-lg font-semibold">
      {branding.data?.logo_url && (
        <img src={branding.data.logo_url} alt="" className="h-8 w-auto" />
      )}
      {title}
    </Link>
  );
}

/** Footer (screens.md): legal link, version and the required markings. */
export function Footer() {
  const branding = useQuery(brandingQuery);
  const version = useQuery(versionQuery);
  return (
    <footer className="flex flex-wrap items-center gap-4 border-t border-border bg-surface px-4 py-1 text-sm text-text-muted">
      <Link to="/legal">Legal</Link>
      {version.data?.version && <span>Version {version.data.version}</span>}
      {branding.data?.required_markings && (
        <span>{branding.data.required_markings}</span>
      )}
    </footer>
  );
}
