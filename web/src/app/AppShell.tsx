import { Outlet, useNavigate, useRouteContext } from "@tanstack/react-router";

import { useLogout } from "@/lib/auth/session";

import { BrandMark, Footer } from "./BrandingShell";
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

  return (
    <div className="flex min-h-screen flex-col bg-bg text-text">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-surface focus:p-2"
      >
        Skip to main content
      </a>
      <header className="flex h-14 items-center justify-between gap-4 border-b border-border bg-surface px-4">
        <BrandMark />
        <div className="flex items-center gap-3">
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
        <LeftRail />
        <main id="main" className="min-w-0 flex-1 p-6">
          <Outlet />
        </main>
      </div>
      <Footer />
    </div>
  );
}
