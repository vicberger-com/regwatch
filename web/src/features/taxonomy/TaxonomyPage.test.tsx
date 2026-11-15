import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

import { flatten } from "./api";

const term = (
  id: string,
  key: string,
  label: string,
  children: unknown[] = [],
) => ({
  id,
  facet_key: "topic",
  key,
  label,
  active: true,
  synonyms: [],
  children,
});
const TOPIC = {
  id: "f1",
  key: "topic",
  label: "Topic",
  value_type: "term",
  multi: true,
  required: false,
  show_in_view_selector: true,
  show_in_filters: true,
  sort_order: 10,
  system: true,
  hidden: false,
  terms: [
    term("t1", "data-protection", "Data protection", [
      term("t2", "privacy", "Privacy"),
    ]),
  ],
};
const NOTES = {
  ...TOPIC,
  id: "f2",
  key: "notes",
  label: "Notes",
  value_type: "text",
  system: false,
  show_in_view_selector: false,
  terms: [],
};
const MANAGER = { ...ADMIN, permissions: ["taxonomy.read", "taxonomy.manage"] };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("taxonomy screen", () => {
  it("shows facets and the nested term tree", async () => {
    fakeApi({
      "GET /auth/me": [200, MANAGER],
      "GET /taxonomy/facets": [200, [TOPIC, NOTES]],
    });
    renderAt("/admin/taxonomy");
    const tree = await screen.findByRole("list", { name: "Terms of Topic" });
    const top = within(tree).getByText("Data protection").closest("li");
    expect(top && within(top).getByText("Privacy")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Topic (system)" }),
    ).toHaveAttribute("aria-current", "true");
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Notes" }));
    expect(
      await screen.findByRole("heading", { name: "Notes" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Add term to Notes" }),
    ).toBeNull(); // text facet
  });

  it("shows no edit forms to taxonomy.read holders", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["taxonomy.read"] }],
      "GET /taxonomy/facets": [200, [TOPIC]],
    });
    renderAt("/admin/taxonomy");
    await screen.findByRole("list", { name: "Terms of Topic" });
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.getByRole("link", { name: "Taxonomy" })).toBeInTheDocument();
  });

  it("refuses users without taxonomy.read", async () => {
    fakeApi({ "GET /auth/me": [200, { ...ADMIN, permissions: [] }] });
    renderAt("/admin/taxonomy");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
  });

  it("reports a failed load", async () => {
    fakeApi({
      "GET /auth/me": [200, MANAGER],
      "GET /taxonomy/facets": [500, problem(500, "Boom")],
    });
    renderAt("/admin/taxonomy");
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });

  it("flattens a term tree depth first", () => {
    const flat = flatten(TOPIC.terms as never);
    expect(flat.map((f) => [f.term.key, f.depth])).toEqual([
      ["data-protection", 0],
      ["privacy", 1],
    ]);
  });
});
