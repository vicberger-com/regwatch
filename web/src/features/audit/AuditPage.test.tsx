import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

import { VALUE_MAX } from "./AuditPage";

const ME = { ...ADMIN, permissions: ["audit.read"] };
const ROW = {
  id: "a1",
  occurred_at: "2026-11-15T10:20:30.123Z",
  actor_email: "admin@example.org",
  action: "role.update",
  entity_type: "role",
  entity_id: "r-aud",
  before: { permissions: ["audit.read"] },
  after: { permissions: ["audit.read", "<img src=x onerror=alert(1)>"] },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("audit log screen", () => {
  it("shows entries with before and after values as text", async () => {
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/audit": [
        200,
        { items: [ROW], total: 1, page: 1, page_size: 50 },
      ],
    });
    renderAt("/admin/audit");
    const table = await screen.findByRole("table", { name: "Audit entries" });
    const row = within(table).getAllByRole("row")[1];
    if (!row) throw new Error("no data row");
    expect(within(row).getByText("2026-11-15 10:20:30")).toBeInTheDocument();
    expect(within(row).getByText("role.update")).toBeInTheDocument();
    expect(
      within(row).getByText(/<img src=x onerror=alert\(1\)>/),
    ).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull(); // shown as text, never as markup
  });

  it("filters and pages", async () => {
    const seen: string[] = [];
    fakeApi({ "GET /auth/me": [200, ME] });
    const fake = globalThis.fetch;
    vi.stubGlobal("fetch", (request: Request) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith("/admin/audit")) {
        seen.push(url.search);
        const page = Number(url.searchParams.get("page"));
        const body = {
          items: [{ ...ROW, id: `p${String(page)}` }],
          total: 120,
          page,
          page_size: 50,
        };
        return Promise.resolve(
          new Response(JSON.stringify(body), {
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return fake(request);
    });
    renderAt("/admin/audit");
    const user = userEvent.setup();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "120 entries · page 1 of 3",
    );
    const form = screen.getByRole("form", { name: "Filter audit log" });
    await user.type(within(form).getByLabelText("Action"), "role.update");
    await user.type(
      within(form).getByLabelText("From (UTC day)"),
      "2026-11-01",
    );
    await user.click(
      within(form).getByRole("button", { name: "Apply filters" }),
    );
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("page 2 of 3");
    });
    const last = new URLSearchParams(seen.at(-1));
    expect(last.get("action")).toBe("role.update");
    expect(last.get("from")).toBe("2026-11-01T00:00:00Z");
    expect(last.get("page")).toBe("2");
    expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled();
  });

  it("is closed without audit.read", async () => {
    fakeApi({ "GET /auth/me": [200, { ...ADMIN, permissions: [] }] });
    renderAt("/admin/audit");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
  });

  it("reports a failed load", async () => {
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/audit": [500, problem(500, "Boom")],
    });
    renderAt("/admin/audit");
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });
  it("hides earlier rows once a later page fails, such as after the session ends", async () => {
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/audit": [
        200,
        { items: [ROW], total: 120, page: 1, page_size: 50 },
      ],
    });
    const fake = globalThis.fetch;
    vi.stubGlobal("fetch", (request: Request) =>
      new URL(request.url).searchParams.get("page") === "2"
        ? Promise.resolve(
            new Response(JSON.stringify(problem(401, "Sign in again.")), {
              status: 401,
              headers: { "Content-Type": "application/problem+json" },
            }),
          )
        : fake(request),
    );
    renderAt("/admin/audit");
    const user = userEvent.setup();
    await screen.findByRole("table", { name: "Audit entries" });
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Sign in again.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Audit entries" })).toBeNull();
    expect(screen.queryByText("role.update")).toBeNull();
  });

  it("shortens a very large value", async () => {
    const big = {
      ...ROW,
      before: null,
      after: { text: "x".repeat(VALUE_MAX * 2) },
    };
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/audit": [
        200,
        { items: [big], total: 1, page: 1, page_size: 50 },
      ],
    });
    renderAt("/admin/audit");
    const more = await screen.findByText(/more characters/);
    expect(more.textContent.length).toBeLessThan(VALUE_MAX + 100);
  });
  it("filters by actor when the users list is available (U-M1-3)", async () => {
    const seen: string[] = [];
    fakeApi({
      "GET /auth/me": [
        200,
        { ...ME, permissions: ["audit.read", "users.manage"] },
      ],
      "GET /admin/users": [
        200,
        {
          items: [
            {
              id: "u-1",
              email: "ana@example.org",
              display_name: "Ana",
              status: "active",
              roles: [],
              last_login_at: null,
            },
          ],
          total: 1,
          page: 1,
          page_size: 200,
        },
      ],
    });
    const fake = globalThis.fetch;
    vi.stubGlobal("fetch", (request: Request) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith("/admin/audit")) {
        seen.push(url.search);
        const body = { items: [ROW], total: 1, page: 1, page_size: 50 };
        return Promise.resolve(
          new Response(JSON.stringify(body), {
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return fake(request);
    });
    renderAt("/admin/audit");
    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: "Filter audit log" });
    await user.selectOptions(
      await within(form).findByLabelText("Actor"),
      "u-1",
    );
    await user.click(
      within(form).getByRole("button", { name: "Apply filters" }),
    );
    await vi.waitFor(() => {
      expect(new URLSearchParams(seen.at(-1)).get("actor")).toBe("u-1");
    });
  });

  it("explains the missing actor filter without users.manage", async () => {
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/audit": [
        200,
        { items: [], total: 0, page: 1, page_size: 50 },
      ],
    });
    renderAt("/admin/audit");
    expect(
      await screen.findByText(/needs the users.manage permission/),
    ).toBeInTheDocument();
  });

  it("exports every matching page as CSV, and says when it stops at the cap", async () => {
    const pages: string[] = [];
    fakeApi({ "GET /auth/me": [200, ME] });
    const fake = globalThis.fetch;
    vi.stubGlobal("fetch", (request: Request) => {
      const url = new URL(request.url);
      if (!url.pathname.endsWith("/admin/audit")) return fake(request);
      const size = Number(url.searchParams.get("page_size"));
      const page = Number(url.searchParams.get("page"));
      if (size === 200) pages.push(String(page));
      const items = Array.from({ length: size }, (_, i) => ({
        ...ROW,
        id: `${String(page)}-${String(i)}`,
      }));
      const body = { items, total: 20_000, page, page_size: size };
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    const blobs: Blob[] = [];
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: (b: Blob) => {
          blobs.push(b);
          return "blob:audit";
        },
        revokeObjectURL: () => undefined,
      }),
    );
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    renderAt("/admin/audit");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Export CSV" }));
    expect(
      await screen.findByText(/newest 10000 of 20000/),
    ).toBeInTheDocument();
    expect(click).toHaveBeenCalled();
    expect(pages).toHaveLength(50); // 50 pages of 200
    const text = await blobs[0]?.text();
    expect(text?.split("\r\n")).toHaveLength(10_002);
  });
});
