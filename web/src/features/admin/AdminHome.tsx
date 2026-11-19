import { Link, useRouteContext } from "@tanstack/react-router";

import { hasPermission } from "@/lib/auth/session";

/** Cards for each admin area the user may open (screens.md `/admin`). */
const AREAS = [
  {
    to: "/admin/users",
    title: "Users",
    text: "Accounts, roles and temporary passwords.",
    permission: "users.manage",
  },
  {
    to: "/admin/roles",
    title: "Roles",
    text: "Permissions grouped by module.",
    permission: "roles.manage",
  },
  {
    to: "/admin/settings",
    title: "Settings",
    text: "Application settings by area.",
    permission: "settings.manage",
  },
  {
    to: "/admin/branding",
    title: "Branding and legal",
    text: "Logo, title, colour and the legal page.",
    permission: "settings.manage",
  },
  {
    to: "/admin/flags",
    title: "Feature flags",
    text: "Optional features and providers.",
    permission: "settings.manage",
  },
  {
    to: "/admin/audit",
    title: "Audit log",
    text: "Who changed what, with before and after.",
    permission: "audit.read",
  },
  {
    to: "/admin/taxonomy",
    title: "Taxonomy",
    text: "Facets, terms and match rules.",
    permission: "taxonomy.read",
  },
  {
    to: "/admin/jurisdictions",
    title: "Jurisdictions",
    text: "Countries, regions and bodies.",
    permission: "taxonomy.read",
  },
  {
    to: "/admin/sources",
    title: "Sources",
    text: "Capture sources, schedules and runs.",
    permission: "sources.read",
  },
] as const;

export function AdminHome() {
  const { me } = useRouteContext({ from: "/authed" });
  const areas = AREAS.filter((a) => hasPermission(me, a.permission));
  return (
    <>
      <h1 className="text-2xl font-semibold">Settings</h1>
      <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {areas.map((area) => (
          <li key={area.to}>
            <Link
              to={area.to}
              className="block h-full rounded border border-border bg-surface p-4 hover:border-accent"
            >
              <span className="font-semibold">{area.title}</span>
              <span className="mt-1 block text-text-muted">{area.text}</span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
