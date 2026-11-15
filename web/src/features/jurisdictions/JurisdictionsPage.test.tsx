import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem, type Routes } from "@/test/api";
import { renderAt } from "@/test/render";

const READER = { ...ADMIN, permissions: ["taxonomy.read"] };
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
  it("lists jurisdictions by code with region names", async () => {
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
    await userEvent
      .setup()
      .selectOptions(screen.getByLabelText("Kind"), "subdivision");
    expect(rows()).toHaveLength(1);
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
});
