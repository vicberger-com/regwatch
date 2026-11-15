import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

const ROLES = [
  { id: "r1", key: "admin", label: "Admin", permissions: [], system: true },
  { id: "r2", key: "viewer", label: "Viewer", permissions: [], system: true },
];
const VIEWER = {
  id: "0190a000-0000-7000-8000-000000000002",
  email: "vic@example.org",
  display_name: "Vic Viewer",
  status: "active",
  roles: ["viewer"],
  last_login_at: null,
};

function users(list: unknown[]) {
  return { items: list, total: list.length, page: 1, page_size: 200 };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("users screen", () => {
  it("lists users and hides Disable on the admin's own row", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /admin/users": [200, users([ADMIN, VIEWER])],
      "GET /admin/roles": [200, ROLES],
    });
    renderAt("/admin/users");
    const table = await screen.findByRole("table", { name: "Users" });
    const [, own, other] = within(table).getAllByRole("row");
    if (!own || !other) throw new Error("expected a header and two rows");
    expect(within(own).queryByRole("button", { name: /Disable/ })).toBeNull();
    expect(
      within(other).getByRole("button", { name: "Disable vic@example.org" }),
    ).toBeEnabled();
    expect(within(other).getByText("never")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Users" })).toBeInTheDocument();
  });

  it("creates a user with roles and shows the temporary password once", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /admin/users": [200, users([ADMIN])],
      "GET /admin/roles": [200, ROLES],
      "POST /admin/users": [
        201,
        { ...VIEWER, temporary_password: "tmp-SECRET-123" },
      ],
    });
    renderAt("/admin/users");
    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: "Create user" });
    await user.type(within(form).getByLabelText("Email"), "vic@example.org");
    await user.type(within(form).getByLabelText("Name"), "Vic Viewer");
    await user.click(await within(form).findByLabelText("viewer"));
    await user.click(within(form).getByRole("button", { name: "Create user" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Temporary password for vic@example.org: tmp-SECRET-123",
    );
    expect(api.calls.find((c) => c.key === "POST /admin/users")?.body).toEqual({
      email: "vic@example.org",
      display_name: "Vic Viewer",
      roles: ["viewer"],
    });
  });

  it("names the field when the API refuses a new user", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /admin/users": [200, users([ADMIN])],
      "GET /admin/roles": [200, ROLES],
      "POST /admin/users": [
        422,
        {
          ...problem(422, "The request failed validation."),
          errors: [{ field: "email", message: "must be an email address" }],
        },
      ],
    });
    renderAt("/admin/users");
    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: "Create user" });
    await user.type(within(form).getByLabelText("Email"), "nope");
    await user.type(within(form).getByLabelText("Name"), "N");
    await user.click(within(form).getByRole("button", { name: "Create user" }));
    await vi.waitFor(() => {
      expect(within(form).getByRole("alert")).toHaveTextContent(
        "email: must be an email address",
      );
    });
  });

  it("resets a password and disables an account", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /admin/users": [200, users([ADMIN, VIEWER])],
      "GET /admin/roles": [200, ROLES],
      [`POST /admin/users/${VIEWER.id}/reset-password`]: [
        200,
        { temporary_password: "reset-777" },
      ],
      [`PATCH /admin/users/${VIEWER.id}`]: [
        200,
        { ...VIEWER, status: "disabled" },
      ],
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderAt("/admin/users");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", {
        name: "Reset password for vic@example.org",
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("reset-777");
    await user.click(
      screen.getByRole("button", { name: "Disable vic@example.org" }),
    );
    await vi.waitFor(() => {
      expect(
        api.calls.find((c) => c.key === `PATCH /admin/users/${VIEWER.id}`)
          ?.body,
      ).toEqual({
        status: "disabled",
      });
    });
    expect(screen.getByRole("status")).not.toHaveTextContent("reset-777"); // shown once
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining("ends all their sessions"),
    );
  });

  it("tells a user without users.manage that the page is not permitted", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...VIEWER, permissions: ["items.read"] }],
    });
    renderAt("/admin/users");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
    expect(screen.queryByRole("link", { name: "Users" })).toBeNull();
  });

  it("does nothing when a confirmation is cancelled, and offers no reset on one's own row", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /admin/users": [200, users([ADMIN, VIEWER])],
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderAt("/admin/users");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Disable vic@example.org" }),
    );
    await user.click(
      screen.getByRole("button", {
        name: "Reset password for vic@example.org",
      }),
    );
    expect(
      api.calls.filter(
        (c) => c.key.startsWith("PATCH") || c.key.includes("reset"),
      ),
    ).toEqual([]);
    expect(
      screen.queryByRole("button", {
        name: `Reset password for ${ADMIN.email}`,
      }),
    ).toBeNull();
  });

  it("loads every page of users", async () => {
    const many = Array.from({ length: 201 }, (_, i) => ({
      ...VIEWER,
      id: `u${String(i)}`,
      email: `u${String(i)}@example.org`,
    }));
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /admin/users": () => [
        200,
        { items: many.slice(0, 200), total: 201, page: 1, page_size: 200 },
      ],
    });
    const calls: string[] = [];
    const original = globalThis.fetch;
    vi.stubGlobal("fetch", (request: Request) => {
      const url = new URL(request.url);
      calls.push(url.search);
      if (
        url.pathname.endsWith("/admin/users") &&
        url.searchParams.get("page") === "2"
      ) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: many.slice(200),
              total: 201,
              page: 2,
              page_size: 200,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return original(request);
    });
    renderAt("/admin/users");
    expect(await screen.findByText("u200@example.org")).toBeInTheDocument();
    expect(calls.some((q) => q.includes("page=2"))).toBe(true);
  });
});

describe("create form without roles.manage", () => {
  it("explains that roles cannot be listed", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["users.manage"] }],
      "GET /admin/users": [
        200,
        { items: [ADMIN], total: 1, page: 1, page_size: 200 },
      ],
      "GET /admin/roles": [403, problem(403)],
    });
    renderAt("/admin/users");
    expect(
      await screen.findByText(/needs the roles.manage permission/),
    ).toBeInTheDocument();
  });
});

describe("re-verification follow-ups", () => {
  it("keeps temporary passwords only in the visible notice, not in memory", async () => {
    const { QueryClient, QueryClientProvider } =
      await import("@tanstack/react-query");
    const { createMemoryHistory, createRouter, RouterProvider } =
      await import("@tanstack/react-router");
    const { render } = await import("@testing-library/react");
    const { routeTree } = await import("@/app/router");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /admin/users": [200, users([ADMIN, VIEWER])],
      "GET /admin/roles": [200, []],
      [`POST /admin/users/${VIEWER.id}/reset-password`]: [
        200,
        { temporary_password: "MEM-SECRET-9" },
      ],
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const router = createRouter({
      routeTree,
      context: { queryClient },
      history: createMemoryHistory({ initialEntries: ["/admin/users"] }),
    });
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", {
          name: "Reset password for vic@example.org",
        }),
      );
    expect(await screen.findByRole("status")).toHaveTextContent("MEM-SECRET-9");
    const kept = JSON.stringify(
      queryClient
        .getMutationCache()
        .getAll()
        .map((m) => m.state),
    );
    expect(kept).not.toContain("MEM-SECRET-9");
  });

  it("says when the list stops at the loading limit", async () => {
    const many = Array.from({ length: 10_000 }, (_, i) => ({
      ...VIEWER,
      id: `m${String(i)}`,
      email: `m${String(i)}@example.org`,
    }));
    let page = 0;
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /admin/users": () => {
        page += 1;
        return [
          200,
          {
            items: many.slice((page - 1) * 200, page * 200),
            total: 20_000,
            page,
            page_size: 200,
          },
        ];
      },
      "GET /admin/roles": [200, []],
    });
    renderAt("/admin/users");
    expect(
      await screen.findByText(
        /Only the first 10000 users are listed/,
        {},
        { timeout: 15_000 },
      ),
    ).toBeInTheDocument();
  }, 30_000);
});
