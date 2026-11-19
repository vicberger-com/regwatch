import { Link, useRouteContext } from "@tanstack/react-router";

import { ADMIN_AREAS } from "@/app/commands";
import { hasPermission } from "@/lib/auth/session";

export function AdminHome() {
  const { me } = useRouteContext({ from: "/authed" });
  const areas = ADMIN_AREAS.filter((a) => hasPermission(me, a.permission));
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
