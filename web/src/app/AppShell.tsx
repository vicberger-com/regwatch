import {
  Link,
  Outlet,
  useNavigate,
  useRouteContext,
} from "@tanstack/react-router";

import { useLogout } from "@/lib/auth/session";

import { ThemeSwitch } from "./ThemeSwitch";

/** The signed-in frame: skip link, header with user and sign-out, and the routed page. */
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
      <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-4 py-2">
        <Link to="/" className="text-lg font-semibold">
          regwatch
        </Link>
        <div className="flex items-center gap-3">
          <ThemeSwitch />
          <span className="text-text-muted">{me.display_name}</span>
          <button
            type="button"
            className="rounded border border-border px-2 py-1"
            onClick={() => {
              logout.mutate(undefined, {
                onSettled: () => {
                  void navigate({ to: "/login", search: {} });
                },
              });
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <main id="main" className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}
