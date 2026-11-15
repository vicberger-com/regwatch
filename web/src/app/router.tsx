/**
 * Routes (TanStack Router, code-based). Every route except `/login` needs a session: the
 * guard asks `GET /auth/me` once (cached by TanStack Query) and sends anonymous visitors to
 * `/login?next=…` and users with a temporary password to `/change-password`. The API enforces
 * the same rules; the guard only keeps the UI from showing screens that would answer 401/403.
 */
import { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { ChangePasswordPage } from "@/features/auth/ChangePasswordPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { currentUser } from "@/lib/auth/session";

import { AppShell } from "./AppShell";

export interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: () => <Outlet />,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): { next?: string } =>
    typeof search.next === "string" ? { next: search.next } : {},
  component: function Login() {
    const { next } = loginRoute.useSearch();
    return <LoginPage next={next} />;
  },
});

/** Everything below needs a signed-in user. */
const authedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "authed",
  beforeLoad: async ({ context, location }) => {
    const me = await currentUser(context.queryClient);
    // TanStack Router redirects are thrown by design.
    if (!me) {
      // eslint-disable-next-line @typescript-eslint/only-throw-error
      throw redirect({ to: "/login", search: { next: location.href } });
    }
    if (me.must_change_password && location.pathname !== "/change-password") {
      // eslint-disable-next-line @typescript-eslint/only-throw-error
      throw redirect({ to: "/change-password" });
    }
    return { me };
  },
  component: AppShell,
});

const homeRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/",
  component: function Home() {
    const { me } = authedRoute.useRouteContext();
    return (
      <>
        <h1 className="text-2xl font-semibold">Regulatory monitor</h1>
        <p className="mt-2 text-text-muted">
          Signed in as {me.display_name}. The map and item screens arrive with
          M6.
        </p>
      </>
    );
  },
});

const changePasswordRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/change-password",
  component: function ChangePassword() {
    const { me } = authedRoute.useRouteContext();
    return <ChangePasswordPage forced={me.must_change_password ?? false} />;
  },
});

export const routeTree = rootRoute.addChildren([
  loginRoute,
  authedRoute.addChildren([homeRoute, changePasswordRoute]),
]);

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({ routeTree, context: { queryClient } });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
