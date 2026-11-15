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
import { RolesPage } from "@/features/admin/RolesPage";
import { UsersPage } from "@/features/admin/UsersPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { FlagsPage } from "@/features/settings/FlagsPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { TaxonomyPage } from "@/features/taxonomy/TaxonomyPage";
import { currentUser, hasPermission } from "@/lib/auth/session";

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

/** Shown in place of a page the user's roles do not allow; the API refuses it too. */
function NotPermitted() {
  return (
    <p role="alert" className="text-critical">
      You do not have permission to see this page.
    </p>
  );
}

const usersRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/users",
  component: function Users() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "users.manage")) return <NotPermitted />;
    return <UsersPage selfId={me.id} />;
  },
});

const taxonomyRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/taxonomy",
  component: function Taxonomy() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "taxonomy.read")) return <NotPermitted />;
    return <TaxonomyPage canManage={hasPermission(me, "taxonomy.manage")} />;
  },
});

const rolesRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/roles",
  component: function Roles() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "roles.manage")) return <NotPermitted />;
    return <RolesPage />;
  },
});

const flagsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/flags",
  component: function Flags() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "settings.manage")) return <NotPermitted />;
    return <FlagsPage />;
  },
});

const settingsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/settings",
  component: function Settings() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "settings.manage")) return <NotPermitted />;
    return <SettingsPage />;
  },
});

const auditRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/audit",
  component: function Audit() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "audit.read")) return <NotPermitted />;
    return <AuditPage />;
  },
});

export const routeTree = rootRoute.addChildren([
  loginRoute,
  authedRoute.addChildren([
    homeRoute,
    changePasswordRoute,
    usersRoute,
    taxonomyRoute,
    rolesRoute,
    flagsRoute,
    settingsRoute,
    auditRoute,
  ]),
]);

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({ routeTree, context: { queryClient } });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
