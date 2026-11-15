import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem, type Routes } from "@/test/api";
import { renderAt } from "@/test/render";

import { lines } from "./api";

const MANAGER = { ...ADMIN, permissions: ["taxonomy.read", "taxonomy.manage"] };
const PRIVACY = {
  id: "t1",
  facet_key: "topic",
  key: "privacy",
  label: "Privacy",
  active: true,
  synonyms: ["data protection"],
  match_rules: {
    keywords: ["GDPR"],
    regex: ["personal\\s+data"],
    languages: ["en"],
    min_hits: 1,
    weight: 1,
  },
  children: [],
};
const TOPIC = {
  id: "f1",
  key: "topic",
  label: "Topic",
  value_type: "term",
  multi: true,
  required: false,
  show_in_view_selector: true,
  show_in_filters: true,
  sort_order: 0,
  system: false,
  hidden: false,
  terms: [PRIVACY],
};
const BASE = {
  "GET /auth/me": [200, MANAGER],
  "GET /taxonomy/facets": [200, [TOPIC]],
} satisfies Routes;

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openEditor() {
  renderAt("/admin/taxonomy");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Edit Privacy" }));
  return {
    user,
    form: screen.getByRole("form", { name: "Edit term Privacy" }),
  };
}

describe("term editor", () => {
  it("splits lines and drops blanks", () => {
    expect(lines(" a \n\n b ")).toEqual(["a", "b"]);
  });

  it("is offered to managers only", async () => {
    fakeApi({
      ...BASE,
      "GET /auth/me": [200, { ...ADMIN, permissions: ["taxonomy.read"] }],
    });
    renderAt("/admin/taxonomy");
    await screen.findByText("Privacy");
    expect(screen.queryByRole("button", { name: "Edit Privacy" })).toBeNull();
  });

  it("saves label, synonyms and match rules", async () => {
    const api = fakeApi({
      ...BASE,
      "PATCH /taxonomy/terms/t1": [200, PRIVACY],
    });
    const { user, form } = await openEditor();
    expect(within(form).getByLabelText(/Patterns/)).toHaveValue(
      "personal\\s+data",
    );
    await user.type(within(form).getByLabelText(/Keywords/), "\n\nePrivacy");
    await user.clear(within(form).getByLabelText("Minimum hits"));
    await user.type(within(form).getByLabelText("Minimum hits"), "2");
    await user.click(within(form).getByRole("button", { name: "Save term" }));
    expect(await within(form).findByText("Saved.")).toBeInTheDocument();
    expect(
      api.calls.find((c) => c.key === "PATCH /taxonomy/terms/t1")?.body,
    ).toEqual({
      label: "Privacy",
      active: true,
      synonyms: ["data protection"],
      match_rules: {
        keywords: ["GDPR", "ePrivacy"],
        regex: ["personal\\s+data"],
        languages: ["en"],
        min_hits: 2,
        weight: 1,
      },
    });
  });

  it("checks numbers first and shows the API's refusal", async () => {
    const api = fakeApi({
      ...BASE,
      "PATCH /taxonomy/terms/t1": [
        400,
        problem(400, "match_rules.regex[0]: not a valid RE2 pattern"),
      ],
    });
    const { user, form } = await openEditor();
    const hits = within(form).getByLabelText("Minimum hits");
    const weight = within(form).getByLabelText("Weight");
    const save = within(form).getByRole("button", { name: "Save term" });
    await user.clear(hits);
    await user.type(hits, "0");
    await user.click(save);
    expect(within(form).getByRole("alert")).toHaveTextContent("Minimum hits");
    await user.clear(hits);
    await user.type(hits, "1");
    await user.clear(weight);
    await user.click(save);
    expect(within(form).getByRole("alert")).toHaveTextContent("Weight");
    expect(api.calls.some((c) => c.key.startsWith("PATCH"))).toBe(false);
    await user.type(weight, "1");
    await user.click(save);
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "not a valid RE2 pattern",
    );
    await user.click(within(form).getByRole("button", { name: "Close" }));
    expect(
      screen.queryByRole("form", { name: "Edit term Privacy" }),
    ).toBeNull();
  });
  it("tests the saved rules and shows evidence as text", async () => {
    const api = fakeApi({
      ...BASE,
      "POST /taxonomy/terms/t1/test-rules": [
        200,
        { matched: true, confidence: 0.8, evidence: ["<b>GDPR</b>"] },
      ],
    });
    const { user } = await openEditor();
    const test = screen.getByRole("form", { name: "Test rules" });
    await user.type(
      within(test).getByLabelText("Sample text"),
      "The GDPR applies.",
    );
    await user.type(within(test).getByLabelText(/Language/), "en");
    await user.click(within(test).getByRole("button", { name: "Test" }));
    expect(
      await within(test).findByText("Matched, confidence 0.80"),
    ).toBeInTheDocument();
    expect(within(test).getByText("<b>GDPR</b>")).toBeInTheDocument();
    expect(api.calls.at(-1)?.body).toEqual({
      text: "The GDPR applies.",
      language: "en",
    });
  });

  it("reports a failed test", async () => {
    fakeApi({
      ...BASE,
      "POST /taxonomy/terms/t1/test-rules": [
        400,
        problem(400, "text: too long"),
      ],
    });
    const { user } = await openEditor();
    const test = screen.getByRole("form", { name: "Test rules" });
    await user.type(within(test).getByLabelText("Sample text"), "x");
    await user.click(within(test).getByRole("button", { name: "Test" }));
    expect(await within(test).findByRole("alert")).toHaveTextContent(
      "too long",
    );
  });
});
