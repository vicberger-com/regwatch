import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

const MANAGER = {
  ...ADMIN,
  permissions: ["users.manage", "roles.manage", "items.read"],
};
const ROLES = [
  {
    id: "r1",
    key: "admin",
    label: "Admin",
    permissions: ["users.manage", "roles.manage", "items.read"],
    system: true,
  },
  {
    id: "r2",
    key: "analyst",
    label: "Analyst",
    permissions: ["items.read", "reports.build"],
    system: true,
  },
];
const USERS = {
  items: [
    {
      id: "u1",
      email: "vic@example.org",
      display_name: "Vic",
      status: "active",
      roles: ["viewer"],
    },
  ],
  total: 1,
  page: 1,
  page_size: 200,
};
const GROUP = {
  id: "g1",
  key: "eu-policy",
  name: "EU policy team",
  description: null,
  roles: ["analyst"],
  members: [],
  interests: { jurisdictions: [], regions: [], terms: {} },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("groups (M11.4c)", () => {
  it("creates a group, never with an administration role", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, MANAGER],
      "GET /admin/groups": [200, []],
      "GET /admin/roles": [200, ROLES],
      "POST /admin/groups": (body) => [201, { ...GROUP, ...(body as object) }],
    });
    renderAt("/admin/groups");
    const form = await screen.findByRole("form", { name: "New group" });
    expect(
      within(form).getByRole("checkbox", { name: /Admin/ }),
    ).toBeDisabled();
    await userEvent.type(within(form).getByLabelText("Name"), "EU policy team");
    await userEvent.type(within(form).getByLabelText(/^Key/), "eu-policy");
    await userEvent.click(
      within(form).getByRole("checkbox", { name: /Analyst/ }),
    );
    await userEvent.click(
      within(form).getByRole("button", { name: "Create the group" }),
    );
    await waitFor(() => {
      expect(
        api.calls.find((c) => c.key === "POST /admin/groups")?.body,
      ).toEqual({
        key: "eu-policy",
        name: "EU policy team",
        roles: ["analyst"],
      });
    });
  });

  it("says what membership grants, and adds a member", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, MANAGER],
      "GET /admin/groups": [200, [GROUP]],
      "GET /admin/roles": [200, ROLES],
      "GET /admin/users": [200, USERS],
      "PUT /admin/groups/g1/members/u1": [204, undefined],
    });
    renderAt("/admin/groups");
    await userEvent.click(
      await screen.findByRole("button", { name: "Open EU policy team" }),
    );
    const detail = await screen.findByRole("region", {
      name: /EU policy team/,
    });
    expect(
      within(detail).getByText(/Members get: items.read, reports.build/),
    ).toBeVisible();
    await userEvent.selectOptions(
      await within(detail).findByLabelText("Add a member"),
      "u1",
    );
    await userEvent.click(within(detail).getByRole("button", { name: "Add" }));
    await waitFor(() => {
      expect(api.calls.map((c) => c.key)).toContain(
        "PUT /admin/groups/g1/members/u1",
      );
    });
    expect(
      within(detail).getByRole("form", { name: "EU policy team's interests" }),
    ).toBeVisible();
  });

  it("is only for those who manage users", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["items.read"] }],
    });
    renderAt("/admin/groups");
    expect(await screen.findByText(/not permitted|permission/i)).toBeVisible();
  });
});
