import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

// The Puck editor is a large lazy chunk; the page logic is tested around it.
vi.mock("./Editor", () => ({
  default: (props: { onChange: (d: Record<string, unknown>) => void }) => (
    <button
      type="button"
      onClick={() => {
        props.onChange({ root: { props: { title: "Edited" } }, content: [] });
      }}
    >
      Edit the layout
    </button>
  ),
}));

const BUILDER = { ...ADMIN, permissions: ["reports.build", "items.read"] };
const LAYOUT = {
  id: "l1",
  user_id: ADMIN.id,
  name: "Europe weekly",
  layout: { root: { props: { title: "" } }, content: [] },
  data_source: { limit: 500 },
  page_size: "A4",
  orientation: "portrait",
  shared: false,
  version: 3,
};
const OTHERS = {
  ...LAYOUT,
  id: "l2",
  user_id: "someone",
  name: "Team digest",
  shared: true,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("reports (M7.4)", () => {
  it("lists own and shared reports; only one's own can be deleted", async () => {
    fakeApi({
      "GET /auth/me": [200, BUILDER],
      "GET /reports/layouts": [200, [LAYOUT, OTHERS]],
    });
    renderAt("/reports");
    const table = await screen.findByRole("table");
    expect(
      within(table).getByRole("link", { name: "Europe weekly" }),
    ).toBeVisible();
    expect(within(table).getByText("Shared")).toBeVisible();
    expect(
      within(table).getByRole("button", { name: "Delete Europe weekly" }),
    ).toBeVisible();
    expect(
      within(table).queryByRole("button", { name: "Delete Team digest" }),
    ).toBeNull();
  });

  it("saves settings, data source and layout, and previews in a sandbox", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, BUILDER],
      "GET /reports/layouts/l1": [200, LAYOUT],
      "GET /reports/fields": [
        200,
        [
          {
            key: "item.title",
            label: "Title",
            type: "text",
            sortable: true,
            group: "Item",
          },
        ],
      ],
      "GET /views": [200, []],
      "PATCH /reports/layouts/l1": (body) => [
        200,
        { ...LAYOUT, ...(body as object), version: 4 },
      ],
      "POST /reports/layouts/l1/preview": [200, "<p>Rendered</p>"],
    });
    renderAt("/reports/l1");
    const form = await screen.findByRole("form", { name: "Report settings" });
    await userEvent.type(
      within(form).getByLabelText("Data: search words"),
      "nis2",
    );
    await userEvent.selectOptions(
      within(form).getByLabelText("Orientation"),
      "landscape",
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Edit the layout" }),
    );
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(
        api.calls.find((c) => c.key === "PATCH /reports/layouts/l1")?.body,
      ).toMatchObject({
        orientation: "landscape",
        layout: { root: { props: { title: "Edited" } }, content: [] },
        data_source: { query: { q: "nis2" }, limit: 500 },
      });
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Preview the saved version" }),
    );
    const frame = await screen.findByTitle("Report preview");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame.getAttribute("srcdoc")).toContain("Rendered");
  });

  it("is only for those who build reports", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["items.read"] }],
    });
    renderAt("/reports");
    expect(await screen.findByText(/not permitted|permission/i)).toBeVisible();
  });
});
