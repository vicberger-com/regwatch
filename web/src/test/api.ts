/** A fake API for component tests: route `METHOD /path` to a status and JSON body. */
import { vi } from "vitest";

export type Routes = Record<
  string,
  [number, unknown] | ((body: unknown, url: URL) => [number, unknown])
>;

/** Answers every test gets unless it routes the request itself: the map on `/` (M6) and the
 * preferences the shell's idle watch reads (M9). */
const DEFAULTS: Routes = {
  "GET /auth/sso": [200, { enabled: false }],
  "GET /me/preferences": [200, { session_idle_timeout_minutes: 480 }],
  "GET /me/interest-options": [
    200,
    { facets: [], jurisdictions: [], regions: [] },
  ],
  "GET /catalogue": [200, []],
  "GET /feed-requests": [200, []],
  "GET /me/groups": [200, []],
  "GET /map/activity": [
    200,
    {
      period_start: "2026-10-20T00:00:00Z",
      period_end: "2026-11-19T00:00:00Z",
      view_by: "country",
      rows: [],
    },
  ],
};

export function fakeApi(given: Routes) {
  const routes: Routes = { ...DEFAULTS, ...given };
  const calls: {
    key: string;
    body: unknown;
    origin: string | null;
    passive: string | null;
  }[] = [];
  const fetch = vi.fn(async (request: Request) => {
    const url = new URL(request.url);
    const key = `${request.method} ${url.pathname.replace("/api/v1", "")}`;
    const text = await request.text();
    const json = request.headers.get("Content-Type")?.includes("json") ?? false;
    const body: unknown = text && json ? JSON.parse(text) : text || undefined;
    calls.push({
      key,
      body,
      origin: request.headers.get("origin"),
      passive: request.headers.get("X-Regwatch-Passive"),
    });
    const route = routes[key];
    if (route === undefined) throw new Error(`unexpected request ${key}`);
    const [status, payload] =
      typeof route === "function" ? route(body, url) : route;
    const type =
      status >= 400 ? "application/problem+json" : "application/json";
    return new Response(
      payload === undefined ? null : JSON.stringify(payload),
      {
        status,
        headers: { "Content-Type": type },
      },
    );
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, calls };
}

export const ADMIN = {
  id: "0190a000-0000-7000-8000-000000000001",
  email: "admin@example.org",
  display_name: "Ada Admin",
  status: "active",
  roles: ["admin"],
  must_change_password: false,
  permissions: ["users.manage", "taxonomy.manage", "items.read"],
};

export function problem(status: number, detail?: string) {
  return {
    type: "https://regwatch/errors/x",
    title: "Error",
    status,
    ...(detail ? { detail } : {}),
  };
}
