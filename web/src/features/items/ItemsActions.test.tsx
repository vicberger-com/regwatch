import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

const EMPTY = { items: [], total: 0, page: 1, page_size: 25 };

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("items actions (use testing U-M7-3, U-M8-4)", () => {
  it("saves the filtered list as a view, keeping the period as days", async () => {
    const api = fakeApi({
      "GET /auth/me": [
        200,
        { ...ADMIN, permissions: ["items.read", "views.manage_shared"] },
      ],
      "POST /search": [200, EMPTY],
      "POST /views": (body) => [201, { id: "v1", ...(body as object) }],
    });
    renderAt("/items?j=DE&days=7&q=NIS2");
    await userEvent.click(
      await screen.findByRole("button", { name: "Save as view" }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: "View name" }),
      "Germany NIS2",
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Share with everyone" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Saved the view Germany NIS2.",
    );
    expect(api.calls.find((c) => c.key === "POST /views")?.body).toEqual({
      name: "Germany NIS2",
      q: "NIS2",
      filters: { jurisdictions: ["DE"] },
      period_days: 7,
      shared: true,
    });
    expect(screen.queryByRole("button", { name: "Export CSV" })).toBeNull(); // no outputs.csv
  });

  it("exports the filtered list as CSV", async () => {
    const url = vi.fn(() => "blob:csv");
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: url, revokeObjectURL: vi.fn() }),
    );
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const api = fakeApi({
      "GET /auth/me": [
        200,
        { ...ADMIN, permissions: ["items.read", "outputs.csv"] },
      ],
      "POST /search": [200, EMPTY],
      "POST /search/export.csv": [200, "title\r\n"],
    });
    renderAt("/items?j=DE");
    await userEvent.click(
      await screen.findByRole("button", { name: "Export CSV" }),
    );
    await waitFor(() => {
      expect(click).toHaveBeenCalledOnce();
    });
    const sent = api.calls.find((c) => c.key === "POST /search/export.csv")
      ?.body as {
      filters: { jurisdictions: string[] };
    };
    expect(sent.filters.jurisdictions).toEqual(["DE"]);
    expect(url).toHaveBeenCalledOnce();
  });
});
