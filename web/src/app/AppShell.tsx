import { Outlet, useNavigate, useRouteContext } from "@tanstack/react-router";

import { useQuery } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { useEffect } from "react";

import { meQuery, useLogout } from "@/lib/auth/session";

import { setTimeZone } from "@/lib/time/format";

import { applyAppearance, resolve, systemIsDark } from "./appearance";

import { BrandMark, Footer } from "./BrandingShell";
import { IdleWatch } from "./IdleWatch";
import { LeftRail } from "./LeftRail";
import { ThemeSwitch } from "./ThemeSwitch";

/**
 * The signed-in frame (screens.md layout grid): skip link, a 56 px header with the brand, theme,
 * user and sign-out, the left rail of commands, the page and the footer.
 */
export function AppShell() {
  const { me } = useRouteContext({ from: "/authed" });
  const logout = useLogout();
  const navigate = useNavigate();
  // The signed-in user's appearance, applied at once and on every change (M9 acceptance 1);
  // the live query, since the route context keeps the user as it was at sign-in.
  const live = useQuery(meQuery).data ?? me;
  const prefs = live.preferences;
  // Dates in the user's zone (use testing U-M9-1), set while rendering so every date drawn in
  // this render already uses it; idempotent, so repeated renders are harmless.
  setTimeZone(prefs?.timezone);
  useEffect(() => {
    applyAppearance(resolve(prefs, systemIsDark()));
  }, [prefs]);

  return (
    <div className="flex min-h-screen flex-col bg-bg text-text">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-surface focus:p-2"
      >
        Skip to main content
      </a>
      <header className="flex h-14 items-center justify-between gap-4 border-b border-border bg-surface px-4 print:hidden">
        <BrandMark />
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="flex shrink-0 items-center gap-1 rounded border border-border px-2 py-1"
            onClick={() => {
              window.print();
            }}
          >
            <Printer aria-hidden="true" size={16} />
            Print
          </button>
          <ThemeSwitch />
          <span className="max-w-48 truncate text-text-muted">
            {me.display_name}
          </span>
          <button
            type="button"
            className="shrink-0 rounded border border-border px-2 py-1"
            disabled={logout.isPending}
            onClick={() => {
              logout.mutate(undefined, {
                onSuccess: () => {
                  void navigate({ to: "/login", search: {} });
                },
              });
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      {logout.isError && (
        <p
          role="alert"
          className="border-b border-critical bg-surface px-4 py-2 text-critical"
        >
          Sign-out failed, so you are still signed in. Try again; if it keeps
          failing, close the browser.
        </p>
      )}
      <div className="flex flex-1">
        <div className="print:hidden">
          <LeftRail />
        </div>
        <main id="main" className="min-w-0 flex-1 p-6">
          <Outlet />
        </main>
      </div>
      {/* Printed too: it carries the required markings (CP-08). */}
      <Footer />
      <IdleWatch />
    </div>
  );
}
