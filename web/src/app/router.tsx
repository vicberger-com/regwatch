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
import { JurisdictionsPage } from "@/features/jurisdictions/JurisdictionsPage";
import { SourcesPage } from "@/features/sources/SourcesPage";
import { FlagsPage } from "@/features/settings/FlagsPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { BrandingPage } from "@/features/branding/BrandingPage";
import { LegalPage } from "@/features/branding/LegalPage";
import { TaxonomyPage } from "@/features/taxonomy/TaxonomyPage";
import { currentUser, hasPermission } from "@/lib/auth/session";

import { AppShell } from "./AppShell";
import { PublicFrame } from "./PublicFrame";

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
  staticData: { title: "Home" },
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
  staticData: { title: "Change password" },
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
  staticData: { title: "Users" },
  component: function Users() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "users.manage")) return <NotPermitted />;
    return <UsersPage selfId={me.id} />;
  },
});

const taxonomyRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/taxonomy",
  staticData: { title: "Taxonomy" },
  component: function Taxonomy() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "taxonomy.read")) return <NotPermitted />;
    return <TaxonomyPage canManage={hasPermission(me, "taxonomy.manage")} />;
  },
});

const jurisdictionsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/jurisdictions",
  staticData: { title: "Jurisdictions" },
  component: function Jurisdictions() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "taxonomy.read")) return <NotPermitted />;
    return (
      <JurisdictionsPage canManage={hasPermission(me, "taxonomy.manage")} />
    );
  },
});

const sourcesRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/sources",
  staticData: { title: "Sources" },
  component: function Sources() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "sources.read")) return <NotPermitted />;
    return (
      <SourcesPage
        canManage={hasPermission(me, "sources.manage")}
        canOverride={hasPermission(me, "sources.override_robots")}
      />
    );
  },
});

const rolesRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/roles",
  staticData: { title: "Roles" },
  component: function Roles() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "roles.manage")) return <NotPermitted />;
    return <RolesPage />;
  },
});

const flagsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/flags",
  staticData: { title: "Feature flags" },
  component: function Flags() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "settings.manage")) return <NotPermitted />;
    return <FlagsPage />;
  },
});

const settingsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/settings",
  staticData: { title: "Settings" },
  component: function Settings() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "settings.manage")) return <NotPermitted />;
    return <SettingsPage />;
  },
});

// Public (CP-08): the sign-in page links here, so it sits outside the signed-in shell.
const legalRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/legal",
  component: function Legal() {
    return (
      <PublicFrame screen="Legal">
        <LegalPage />
      </PublicFrame>
    );
  },
});

const brandingRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/branding",
  staticData: { title: "Branding and legal" },
  component: function BrandingAdmin() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "settings.manage")) return <NotPermitted />;
    return <BrandingPage />;
  },
});

const auditRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/audit",
  staticData: { title: "Audit log" },
  component: function Audit() {
    const { me } = authedRoute.useRouteContext();
    if (!hasPermission(me, "audit.read")) return <NotPermitted />;
    return <AuditPage canListUsers={hasPermission(me, "users.manage")} />;
  },
});

export const routeTree = rootRoute.addChildren([
  loginRoute,
  legalRoute,
  authedRoute.addChildren([
    homeRoute,
    changePasswordRoute,
    usersRoute,
    taxonomyRoute,
    rolesRoute,
    flagsRoute,
    jurisdictionsRoute,
    sourcesRoute,
    settingsRoute,
    brandingRoute,
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

declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    /** The screen name shown in the browser title (use testing U-M0-4). */
    title?: string;
  }
}
