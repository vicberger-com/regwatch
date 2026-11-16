import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem, type Routes } from "@/test/api";
import { renderAt } from "@/test/render";

const ROLES = [
  { id: "r1", key: "admin", label: "Admin", permissions: [], system: true },
  { id: "r2", key: "viewer", label: "Viewer", permissions: [], system: true },
  { id: "r3", key: "analyst", label: "Analyst", permissions: [], system: true },
];
const VIEWER = {
  id: "0190a000-0000-7000-8000-000000000002",
  email: "vic@example.org",
  display_name: "Vic Viewer",
  status: "active",
  roles: ["viewer"],
  last_login_at: null,
};
const LOCKED = {
  ...VIEWER,
  id: "0190a000-0000-7000-8000-000000000003",
  email: "lou@example.org",
  status: "locked",
};
const list = (items: unknown[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 200,
});
const BASE = {
  "GET /auth/me": [200, ADMIN],
  "GET /admin/users": [200, list([ADMIN, VIEWER, LOCKED])],
  "GET /admin/roles": [200, ROLES],
} satisfies Routes;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("editing users (U-M1-2)", () => {
  it("changes another user's name and roles", async () => {
    const api = fakeApi({
      ...BASE,
      [`PATCH /admin/users/${VIEWER.id}`]: [
        200,
        { ...VIEWER, display_name: "Vic V.", roles: ["analyst"] },
      ],
    });
    renderAt("/admin/users");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Edit vic@example.org" }),
    );
    const form = screen.getByRole("form", { name: "Edit vic@example.org" });
    expect(within(form).getByRole("heading")).toHaveFocus(); // U-M0-3
    await user.clear(within(form).getByLabelText("Name"));
    await user.type(within(form).getByLabelText("Name"), "Vic V.");
    await user.click(within(form).getByLabelText("viewer"));
    await user.click(within(form).getByLabelText("analyst"));
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Saved vic@example.org."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Edit vic@example.org" }),
    ).toBeNull();
    expect(api.calls.find((c) => c.key.startsWith("PATCH"))?.body).toEqual({
      display_name: "Vic V.",
      roles: ["analyst"],
    });
  });

  it("edits only the name on one's own row, and closes on Escape", async () => {
    const api = fakeApi(BASE);
    renderAt("/admin/users");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: `Edit ${ADMIN.email}` }),
    );
    const form = screen.getByRole("form", { name: `Edit ${ADMIN.email}` });
    expect(within(form).queryByRole("checkbox")).toBeNull();
    expect(
      within(form).getByText(/changed by another administrator/),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("form", { name: `Edit ${ADMIN.email}` }),
    ).toBeNull();
    await vi.waitFor(() => {
      expect(
        screen.getByRole("button", { name: `Edit ${ADMIN.email}` }),
      ).toHaveFocus(); // focus returns to the opener (peer review of PR 68)
    });
    expect(api.calls.some((c) => c.key.startsWith("PATCH"))).toBe(false);
  });

  it("shows the API's refusal", async () => {
    fakeApi({
      ...BASE,
      [`PATCH /admin/users/${VIEWER.id}`]: [
        403,
        problem(403, "You cannot grant roles you do not hold."),
      ],
    });
    renderAt("/admin/users");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Edit vic@example.org" }),
    );
    const form = screen.getByRole("form", { name: "Edit vic@example.org" });
    await user.click(within(form).getByLabelText("admin"));
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "grant roles you do not hold",
    );
  });

  it("labels a locked account's action Unlock (U-M1-7)", async () => {
    fakeApi(BASE);
    renderAt("/admin/users");
    expect(
      await screen.findByRole("button", { name: "Unlock lou@example.org" }),
    ).toHaveTextContent("Unlock");
  });
});
