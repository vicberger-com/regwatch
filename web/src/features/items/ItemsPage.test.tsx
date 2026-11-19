import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

import { parseItemsSearch, toQuery } from "./ItemsPage";
import { safeUrl } from "./ItemPage";

const ITEM = {
  id: "0190a000-0000-7000-8000-0000000000a1",
  title: "NIS2 Umsetzung",
  title_en: "NIS2 implementation",
  canonical_url: "https://bsi.example/nis2",
  source_id: "0190a000-0000-7000-8000-0000000000b1",
  source_name: "BSI",
  last_changed_at: "2026-11-18T09:00:00Z",
  published_at: "2026-11-01T09:00:00Z",
  status: "updated",
  severity: "notable",
  jurisdictions: [{ code: "DE", name: "Germany" }],
  summary: "Pflichten für Betreiber",
  highlights: { title: ["<mark>NIS2</mark> Umsetzung"] },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("items search parameters", () => {
  it("keeps only valid values", () => {
    expect(
      parseItemsSearch({
        q: "  ",
        j: "de,FR",
        days: "30",
        sort: "title_asc",
        page: "2",
      }),
    ).toEqual({
      j: "DE,FR",
      days: 30,
      sort: "title_asc",
      page: 2,
    });
    expect(
      parseItemsSearch({ j: "<script>", days: "0", sort: "drop", page: "-1" }),
    ).toEqual({});
  });

  it("builds the search query, relevance only with words", () => {
    const now = new Date("2026-11-19T00:00:00Z");
    expect(toQuery({ j: "DE", days: 30 }, now)).toMatchObject({
      filters: {
        jurisdictions: ["DE"],
        changed: { from: "2026-10-20T00:00:00.000Z" },
      },
      sort: "last_changed_desc",
      highlight: false,
    });
    expect(toQuery({ q: "nis2" }, now)).toMatchObject({
      q: "nis2",
      sort: "relevance",
      highlight: true,
    });
  });
});

describe("items table", () => {
  it("lists items with highlights, a count and sortable columns, and searches by words", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "POST /search": [
        200,
        { items: [ITEM], total: 1, page: 1, page_size: 25 },
      ],
    });
    renderAt("/items?q=nis2");
    const table = await screen.findByRole("table");
    expect(await within(table).findByText("1 item")).toBeInTheDocument();
    const link = within(table).getByRole("link", { name: "NIS2 Umsetzung" });
    expect(link).toHaveAttribute("href", `/items/${ITEM.id}`);
    expect(within(link).getByText("NIS2").tagName).toBe("MARK");
    expect(within(table).getByText("NIS2 implementation")).toBeInTheDocument();
    expect(
      within(table).getByRole("columnheader", { name: "Last changed" }),
    ).not.toHaveAttribute("aria-sort");
    const box = screen.getByRole("searchbox", { name: "Search items" });
    await userEvent.clear(box);
    await userEvent.type(box, "incident reporting{Enter}");
    await waitFor(() => {
      expect(
        api.calls.some(
          (c) =>
            (c.body as { q?: string } | undefined)?.q === "incident reporting",
        ),
      ).toBe(true);
    });
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "title_asc");
    await waitFor(() => {
      expect(
        screen.getByRole("columnheader", { name: "Title" }),
      ).toHaveAttribute("aria-sort", "ascending");
    });
  });

  it("opens an item with its summary and only an http(s) source link", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      [`GET /items/${ITEM.id}`]: [200, ITEM],
    });
    renderAt(`/items/${ITEM.id}`);
    expect(
      await screen.findByRole("heading", { level: 1, name: "NIS2 Umsetzung" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Pflichten für Betreiber")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Original page/ })).toHaveAttribute(
      "rel",
      "noopener noreferrer nofollow",
    );
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("data:text/html,x")).toBeNull();
    expect(safeUrl("https://ok.example/a")).toBe("https://ok.example/a");
    expect(safeUrl("https://user:pw@ok.example/a")).toBeNull();
    expect(
      screen.getByRole("link", { name: /Original page on bsi.example/ }),
    ).toBeInTheDocument();
  });
});

describe("items permissions", () => {
  it.each([[[]], [["users.manage"]]])(
    "refuses /items without items.read (%j)",
    async (permissions) => {
      const api = fakeApi({ "GET /auth/me": [200, { ...ADMIN, permissions }] });
      const router = renderAt("/items");
      await waitFor(() => {
        expect(router.state.status).toBe("idle");
      });
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "do not have permission",
      );
      const rail = screen.getByRole("navigation", { name: "Main" });
      expect(within(rail).queryByRole("link", { name: "Items" })).toBeNull();
      expect(api.calls.map((c) => c.key)).not.toContain("POST /search");
    },
  );

  it.each([[[]], [["users.manage"]]])(
    "refuses /items/:id without items.read (%j)",
    async (permissions) => {
      const api = fakeApi({ "GET /auth/me": [200, { ...ADMIN, permissions }] });
      const router = renderAt(`/items/${ITEM.id}`);
      await waitFor(() => {
        expect(router.state.status).toBe("idle");
      });
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "do not have permission",
      );
      expect(
        screen.queryByRole("heading", { level: 1, name: "NIS2 Umsetzung" }),
      ).toBeNull();
      expect(
        api.calls.map((c) => c.key).filter((k) => k.startsWith("GET /items/")),
      ).toEqual([]);
    },
  );

  it("shows the title when a highlight is not text", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "POST /search": [
        200,
        {
          items: [{ ...ITEM, highlights: { title: [42] } }],
          total: 1,
          page: 1,
          page_size: 25,
        },
      ],
    });
    renderAt("/items?q=nis2");
    expect(
      await screen.findByRole("link", { name: "NIS2 Umsetzung" }),
    ).toBeInTheDocument();
  });
});
