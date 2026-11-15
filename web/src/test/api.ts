/** A fake API for component tests: route `METHOD /path` to a status and JSON body. */
import { vi } from "vitest";

export type Routes = Record<
  string,
  [number, unknown] | ((body: unknown) => [number, unknown])
>;

export function fakeApi(routes: Routes) {
  const calls: { key: string; body: unknown; origin: string | null }[] = [];
  const fetch = vi.fn(async (request: Request) => {
    const url = new URL(request.url);
    const key = `${request.method} ${url.pathname.replace("/api/v1", "")}`;
    const text = await request.text();
    const json = request.headers.get("Content-Type")?.includes("json") ?? false;
    const body: unknown = text && json ? JSON.parse(text) : text || undefined;
    calls.push({ key, body, origin: request.headers.get("origin") });
    const route = routes[key];
    if (route === undefined) throw new Error(`unexpected request ${key}`);
    const [status, payload] = typeof route === "function" ? route(body) : route;
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
  permissions: ["users.manage", "taxonomy.manage"],
};

export function problem(status: number, detail?: string) {
  return {
    type: "https://regwatch/errors/x",
    title: "Error",
    status,
    ...(detail ? { detail } : {}),
  };
}
