import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem, type Routes } from "@/test/api";
import { renderAt } from "@/test/render";

const READER = { ...ADMIN, permissions: ["taxonomy.read"] };
const MANAGER = { ...ADMIN, permissions: ["taxonomy.read", "taxonomy.manage"] };
const DE = {
  id: "1",
  code: "DE",
  name: "Germany",
  kind: "country",
  region_code: "155",
  active: true,
};
const BY = {
  id: "2",
  code: "DE-BY",
  name: "Bavaria",
  kind: "subdivision",
  parent_code: "DE",
  active: false,
};
const EU = {
  id: "3",
  code: "EU",
  name: "European Union",
  kind: "supranational",
  active: true,
};
const BASE = {
  "GET /jurisdictions": [200, [EU, BY, DE]],
  "GET /jurisdictions/regions": [
    200,
    [{ code: "155", name: "Western Europe", jurisdiction_codes: ["DE"] }],
  ],
} satisfies Routes;

afterEach(() => {
  vi.unstubAllGlobals();
});

function rows() {
  return within(screen.getByRole("table", { name: "Jurisdictions" }))
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.textContent);
}

describe("jurisdictions screen", () => {
  it("lists jurisdictions by code with region names, read-only for readers", async () => {
    fakeApi({ "GET /auth/me": [200, READER], ...BASE });
    renderAt("/admin/jurisdictions");
    await screen.findByRole("table", { name: "Jurisdictions" });
    await vi.waitFor(() => {
      expect(rows()[0]).toContain("Western Europe");
    });
    expect(rows()).toEqual([
      "DEGermanycountryWestern EuropeYes",
      "DE-BYBavariasubdivision of DENo",
      "EUEuropean UnionsupranationalYes",
    ]);
    expect(screen.queryByRole("button", { name: /Edit|Create/ })).toBeNull();
    await userEvent
      .setup()
      .selectOptions(screen.getByLabelText("Kind"), "subdivision");
    expect(rows()).toHaveLength(1);
  });

  it("creates a subdivision with its parent country", async () => {
    const sent: unknown[] = [];
    fakeApi({ "GET /auth/me": [200, MANAGER], ...BASE });
    const fake = globalThis.fetch;
    vi.stubGlobal("fetch", async (request: Request) => {
      if (request.method === "POST") {
        sent.push(await request.json());
        return new Response(JSON.stringify(BY), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      return fake(request);
    });
    renderAt("/admin/jurisdictions");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Create jurisdiction" }),
    );
    const form = screen.getByRole("form", { name: "Create jurisdiction" });
    await user.type(within(form).getByLabelText("Code"), "DE-BE");
    await user.type(within(form).getByLabelText("Name"), "Berlin");
    await user.selectOptions(
      within(form).getByLabelText("Kind"),
      "subdivision",
    );
    await user.selectOptions(
      within(form).getByLabelText("Parent country"),
      "DE",
    );
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => {
      expect(
        screen.queryByRole("form", { name: "Create jurisdiction" }),
      ).toBeNull();
    });
    expect(sent).toEqual([
      {
        code: "DE-BE",
        kind: "subdivision",
        name: "Berlin",
        parent_code: "DE",
        region_code: null,
        geometry_ref: null,
        active: true,
      },
    ]);
  });

  it("edits without changing code or kind, and shows a refusal", async () => {
    fakeApi({
      "GET /auth/me": [200, MANAGER],
      ...BASE,
      "PATCH /jurisdictions/DE": [
        400,
        problem(400, "geometry_ref: a Natural Earth feature id, such as DEU"),
      ],
    });
    renderAt("/admin/jurisdictions");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit DE" }));
    const form = screen.getByRole("form", { name: "Edit DE" });
    expect(within(form).getByLabelText("Code")).toBeDisabled();
    expect(within(form).getByLabelText("Kind")).toBeDisabled();
    await user.type(within(form).getByLabelText("Map feature id"), "bad id");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Natural Earth feature id",
    );
    await user.click(within(form).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("form", { name: "Edit DE" })).toBeNull();
  });

  it("is closed without taxonomy.read", async () => {
    fakeApi({ "GET /auth/me": [200, { ...ADMIN, permissions: [] }] });
    renderAt("/admin/jurisdictions");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
  });

  it("reports a failed load", async () => {
    fakeApi({
      "GET /auth/me": [200, READER],
      "GET /jurisdictions": [500, problem(500, "Boom")],
      "GET /jurisdictions/regions": [200, []],
    });
    renderAt("/admin/jurisdictions");
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });
  it("moves focus into the edit form, closes on Escape and returns focus (PR 46 review)", async () => {
    fakeApi({ "GET /auth/me": [200, MANAGER], ...BASE });
    renderAt("/admin/jurisdictions");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit DE" }));
    const form = screen.getByRole("form", { name: "Edit DE" });
    expect(
      within(form).getByRole("heading", { name: "Edit DE" }),
    ).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("form", { name: "Edit DE" })).toBeNull();
    await vi.waitFor(() => {
      expect(screen.getByRole("button", { name: "Edit DE" })).toHaveFocus();
    });
  });
});
