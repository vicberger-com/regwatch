import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem, type Routes } from "@/test/api";
import { renderAt } from "@/test/render";

const MANAGER = { ...ADMIN, permissions: ["taxonomy.read", "taxonomy.manage"] };
const term = (
  id: string,
  label: string,
  children: unknown[] = [],
  active = true,
) => ({
  id,
  facet_key: "topic",
  key: label.toLowerCase(),
  label,
  active,
  synonyms: [],
  children,
});
const COOKIES = term("t2", "Cookies");
const PRIVACY = term("t1", "Privacy", [COOKIES]);
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
  terms: [
    PRIVACY,
    term("t3", "Data protection"),
    term("t4", "Retired", [], false),
  ],
};
const BASE = {
  "GET /auth/me": [200, MANAGER],
  "GET /taxonomy/facets": [200, [TOPIC]],
} satisfies Routes;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function open(label: string) {
  renderAt("/admin/taxonomy");
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", { name: `Edit ${label}` }),
  );
  return {
    user,
    group: screen.getByRole("group", { name: `Merge or delete ${label}` }),
  };
}

describe("term merge and delete", () => {
  it("offers only active terms outside the term's own branch", async () => {
    fakeApi(BASE);
    const { group } = await open("Privacy");
    const options = within(
      within(group).getByLabelText("Merge into"),
    ).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "(choose a term)",
      "Data protection",
    ]);
    expect(within(group).getByRole("button", { name: "Merge" })).toBeDisabled();
  });

  it("merges after confirming and reports how many items moved", async () => {
    const api = fakeApi({
      ...BASE,
      "POST /taxonomy/terms/t2/merge": [200, { items_moved: 7 }],
    });
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValue(true);
    const { user, group } = await open("Cookies");
    await user.selectOptions(within(group).getByLabelText("Merge into"), "t3");
    await user.click(within(group).getByRole("button", { name: "Merge" }));
    expect(api.calls.some((c) => c.key.endsWith("/merge"))).toBe(false);
    await user.click(within(group).getByRole("button", { name: "Merge" }));
    expect(
      await screen.findByText(
        "Merged into Data protection; 7 items re-tagged.",
      ),
    ).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(api.calls.find((c) => c.key.endsWith("/merge"))?.body).toEqual({
      into_term_id: "t3",
    });
    expect(
      screen.queryByRole("group", { name: "Merge or delete Cookies" }),
    ).toBeNull();
  });

  it("deletes after confirming", async () => {
    const api = fakeApi({
      ...BASE,
      "DELETE /taxonomy/terms/t3": [204, undefined],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { user, group } = await open("Data protection");
    await user.click(
      within(group).getByRole("button", { name: "Delete term" }),
    );
    expect(
      await screen.findByText(/Data protection deleted, or deactivated/),
    ).toBeInTheDocument();
    expect(api.calls.some((c) => c.key === "DELETE /taxonomy/terms/t3")).toBe(
      true,
    );
  });

  it("does not delete without confirmation, and shows a refusal", async () => {
    const api = fakeApi({
      ...BASE,
      "POST /taxonomy/terms/t2/merge": [
        400,
        problem(400, "into_term_id: the target term is inactive"),
      ],
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { user, group } = await open("Cookies");
    await user.click(
      within(group).getByRole("button", { name: "Delete term" }),
    );
    expect(api.calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);
    confirm.mockReturnValue(true);
    await user.selectOptions(within(group).getByLabelText("Merge into"), "t3");
    await user.click(within(group).getByRole("button", { name: "Merge" }));
    expect(await within(group).findByRole("alert")).toHaveTextContent(
      "target term is inactive",
    );
  });
});
