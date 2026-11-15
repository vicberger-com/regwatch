import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

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
});
