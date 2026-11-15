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
});
