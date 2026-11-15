import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

const PERMS = [
  { key: "users.manage", description: "Create users", module: "M1" },
  { key: "audit.read", description: "Read the audit log", module: "M1" },
  { key: "taxonomy.read", description: "View facets", module: "M2" },
];
const ROLES = [
  {
    id: "r-admin",
    key: "admin",
    label: "Admin",
    permissions: PERMS.map((p) => p.key),
    system: true,
  },
  {
    id: "r-aud",
    key: "auditor",
    label: "Auditor",
    permissions: ["audit.read"],
    system: false,
  },
];
const ME = {
  ...ADMIN,
  permissions: ["roles.manage", ...PERMS.map((p) => p.key)],
};

function baseApi(extra: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({
    "GET /auth/me": [200, ME],
    "GET /admin/roles": [200, ROLES],
    "GET /admin/permissions": [200, PERMS],
    ...extra,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("roles screen", () => {
  it("edits a role's permissions, grouped by module", async () => {
    const api = baseApi({ "PATCH /admin/roles/r-aud": [200, ROLES[1]] });
    renderAt("/admin/roles");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Edit Auditor" }),
    );
    const form = screen.getByRole("form", { name: "Edit role Auditor" });
    expect(within(form).getByRole("group", { name: "M1" })).toBeInTheDocument();
    expect(within(form).getByRole("group", { name: "M2" })).toBeInTheDocument();
    await user.click(
      within(form).getByRole("checkbox", { name: /taxonomy\.read/ }),
    );
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => {
      expect(
        api.calls.find((c) => c.key === "PATCH /admin/roles/r-aud")?.body,
      ).toEqual({
        label: "Auditor",
        permissions: ["audit.read", "taxonomy.read"],
      });
    });
  });

  it("creates a role and shows the API's reason when refused", async () => {
    const api = baseApi({
      "POST /admin/roles": [
        403,
        problem(403, "You cannot grant permissions you do not hold: x."),
      ],
    });
    renderAt("/admin/roles");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Create role" }),
    );
    const form = screen.getByRole("form", { name: "Create role" });
    await user.type(within(form).getByLabelText(/Key/), "editors");
    await user.type(within(form).getByLabelText("Label"), "Editors");
    await user.click(
      within(form).getByRole("checkbox", { name: /users\.manage/ }),
    );
    await user.click(within(form).getByRole("button", { name: "Create" }));
    await vi.waitFor(() => {
      expect(within(form).getByRole("alert")).toHaveTextContent("do not hold");
    });
    expect(api.calls.find((c) => c.key === "POST /admin/roles")?.body).toEqual({
      key: "editors",
      label: "Editors",
      permissions: ["users.manage"],
    });
  });

  it("deletes a custom role after confirmation and never offers it for system roles", async () => {
    const api = baseApi({ "DELETE /admin/roles/r-aud": [204, undefined] });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderAt("/admin/roles");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit Admin" }));
    const adminForm = screen.getByRole("form", { name: "Edit role Admin" });
    expect(
      within(adminForm).queryByRole("button", { name: "Delete role" }),
    ).toBeNull();
    expect(
      within(adminForm).getByText(/always holds every permission/),
    ).toBeInTheDocument();
    expect(
      within(adminForm).getByRole("checkbox", { name: /audit\.read/ }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Edit Auditor" }));
    await user.click(screen.getByRole("button", { name: "Delete role" }));
    expect(confirm).toHaveBeenCalledWith("Delete the role Auditor?");
    await vi.waitFor(() => {
      expect(api.calls.some((c) => c.key === "DELETE /admin/roles/r-aud")).toBe(
        true,
      );
    });
  });

  it("is closed without roles.manage", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["users.manage"] }],
    });
    renderAt("/admin/roles");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
    expect(screen.queryByRole("link", { name: "Roles" })).toBeNull();
  });

  it("reports a failed load", async () => {
    baseApi({ "GET /admin/permissions": [500, problem(500, "Boom")] });
    renderAt("/admin/roles");
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });
});
