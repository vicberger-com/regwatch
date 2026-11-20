import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { engines } from "@/test/fakeEngine";
import { renderAt } from "@/test/render";

const ACTIVITY = {
  period_start: "2026-10-20T00:00:00Z",
  period_end: "2026-11-19T00:00:00Z",
  view_by: "country",
  rows: [
    {
      code: "DE",
      count: 3,
      last_changed_at: "2026-11-18T09:00:00Z",
      max_severity: "major",
    },
    {
      code: "FR",
      count: 1,
      last_changed_at: "2026-10-22T09:00:00Z",
      max_severity: "info",
    },
    {
      code: "EU",
      count: 2,
      last_changed_at: "2026-11-10T09:00:00Z",
      max_severity: "notable",
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
  engines.length = 0;
});

const engine = async () => {
  await waitFor(() => {
    expect(engines.length).toBeGreaterThan(0);
  });
  const last = engines.at(-1);
  if (!last) throw new Error("no engine");
  return last;
};

describe("map page", () => {
  it("shades jurisdictions with changes and leaves the others neutral (acceptance 1)", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    expect(
      await screen.findByText(
        "3 jurisdictions with changes in the last 30 days",
      ),
    ).toHaveAttribute("role", "status");
    const map = await engine();
    await waitFor(() => {
      expect(map.steps.get("DE")).toBe(4);
    });
    expect(map.steps.get("FR")).toBe(1);
    expect(map.steps.has("US")).toBe(false); // neutral: no row
  });

  it("lists the same jurisdictions newest first, and the keyboard selects them (acceptance 5)", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    const list = await screen.findByRole("listbox", { name: /newest first/ });
    const options = within(list).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      expect.stringContaining("Germany"),
      expect.stringContaining("European Union"),
      expect.stringContaining("France"),
    ]);
    expect(options[0]).toHaveTextContent("3 items changed");
    expect(options[0]).toHaveTextContent("highest severity major");
    list.focus();
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    const map = await engine();
    expect(map.selected).toBe("EU");
    map.on.onSelect("FR"); // a click on the map selects in the list
    await waitFor(() => {
      expect(options[2]).toHaveAttribute("aria-selected", "true");
    });
  });

  it("asks again for another period and recolours by count", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    await screen.findByRole("listbox");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "90");
    await waitFor(() => {
      expect(api.calls.some((c) => c.key === "GET /map/activity")).toBe(true);
    });
    expect(
      api.fetch.mock.calls.some(
        ([r]) => new URL(r.url).searchParams.get("period_days") === "90",
      ),
    ).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText("Colour by"), "count");
    const map = await engine();
    await waitFor(() => {
      expect(map.steps.get("FR")).toBe(2); // 1 of at most 3, on a log scale
    });
    expect(map.steps.get("DE")).toBe(4);
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent(
      "Most changes",
    );
  });

  it("sends an administrator without items.read to the settings home, with no Map link", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["users.manage"] }],
    });
    renderAt("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Settings" }),
    ).toBeInTheDocument();
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).queryByRole("link", { name: "Map" })).toBeNull();
  });

  it("opens a panel for the selected jurisdiction, and Escape returns focus to the list", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /map/activity": [
        200,
        {
          ...ACTIVITY,
          rows: ACTIVITY.rows.map((r) =>
            r.code === "DE"
              ? { ...r, breakdown: { info: 1, notable: 0, major: 2 } }
              : r,
          ),
        },
      ],
      "POST /search": [
        200,
        {
          total: 1,
          page: 1,
          page_size: 10,
          items: [
            {
              id: "0190a000-0000-7000-8000-0000000000a1",
              title: "BSI guidance",
              source_id: "0190a000-0000-7000-8000-0000000000b1",
              last_changed_at: "2026-11-18T09:00:00Z",
              status: "new",
              severity: "major",
              jurisdictions: [{ code: "DE" }],
            },
          ],
        },
      ],
    });
    renderAt("/");
    const list = await screen.findByRole("listbox");
    list.focus();
    await userEvent.keyboard("{Enter}");
    const panel = await screen.findByRole("complementary", { name: "Germany" });
    expect(
      within(panel).getByRole("heading", { name: "Germany" }),
    ).toHaveFocus();
    expect(panel).toHaveTextContent("Items changed3");
    expect(panel).toHaveTextContent("major2");
    expect(
      await within(panel).findByRole("link", { name: "BSI guidance" }),
    ).toBeInTheDocument();
    expect(
      within(panel).getByRole("link", { name: /All items for Germany/ }),
    ).toHaveAttribute("href", "/items?j=DE&days=30");
    const body = api.calls.find((c) => c.key === "POST /search")?.body as {
      filters: { jurisdictions: string[] };
      page_size: number;
    };
    expect(body.filters.jurisdictions).toEqual(["DE"]);
    expect(body.page_size).toBe(10);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("complementary", { name: "Germany" })).toBeNull();
    expect(list).toHaveFocus();
  });

  it('re-renders for the view "industry: finance" with finance-tagged activity (acceptance 2)', async () => {
    const api = fakeApi({
      "GET /auth/me": [
        200,
        { ...ADMIN, permissions: ["items.read", "taxonomy.read"] },
      ],
      "GET /taxonomy/facets": [
        200,
        [
          {
            key: "industry",
            label: "Industry",
            show_in_view_selector: true,
            show_in_filters: true,
            terms: [
              {
                id: "t1",
                facet_key: "industry",
                key: "finance",
                label: "Finance",
                active: true,
                children: [],
              },
              {
                id: "t2",
                facet_key: "industry",
                key: "energy",
                label: "Energy",
                active: false,
                children: [],
              },
            ],
          },
          {
            key: "internal",
            label: "Internal",
            show_in_view_selector: false,
            show_in_filters: false,
            terms: [],
          },
        ],
      ],
      "GET /jurisdictions/regions": [
        200,
        [
          {
            code: "155",
            name: "Western Europe",
            jurisdiction_codes: ["DE", "FR"],
          },
        ],
      ],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    const view = await screen.findByLabelText("View");
    await waitFor(() => {
      expect(
        within(view)
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["Country", "Region", "Industry"]);
    });
    await userEvent.selectOptions(view, "facet:industry");
    const value = screen.getByLabelText("Industry");
    expect(
      within(value)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Choose a value", "Finance"]);
    await userEvent.selectOptions(value, "finance");
    await waitFor(() => {
      const urls = api.fetch.mock.calls.map(([r]) => new URL(r.url));
      expect(
        urls.some(
          (u) =>
            u.pathname.endsWith("/map/activity") &&
            u.searchParams.get("filters") ===
              JSON.stringify({ terms: { industry: ["finance"] } }),
        ),
      ).toBe(true);
    });
  });

  it("never asks for facets or regions without taxonomy.read, and offers only the country view", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["items.read"] }],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    const view = await screen.findByLabelText("View");
    await screen.findByRole("listbox");
    expect(
      within(view)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Country"]);
    const keys = api.calls.map((c) => c.key);
    expect(keys).not.toContain("GET /taxonomy/facets");
    expect(keys).not.toContain("GET /jurisdictions/regions");
  });

  it("survives malformed region and facet answers", async () => {
    fakeApi({
      "GET /auth/me": [
        200,
        { ...ADMIN, permissions: ["items.read", "taxonomy.read"] },
      ],
      "GET /taxonomy/facets": [
        200,
        [
          null,
          {
            key: "industry",
            label: "Industry",
            show_in_view_selector: true,
            terms: [null],
          },
        ],
      ],
      "GET /jurisdictions/regions": [
        200,
        [{ code: 155, jurisdiction_codes: "DE" }, null],
      ],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    const view = screen.getByLabelText("View");
    await within(view).findByRole("option", { name: "Industry" });
    await userEvent.selectOptions(view, "facet:industry");
    expect(
      within(screen.getByLabelText("Industry")).getAllByRole("option"),
    ).toHaveLength(1);
  });

  it("shows the same data as a sortable table", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    await screen.findByRole("listbox");
    await userEvent.click(screen.getByRole("radio", { name: "Table" }));
    const table = screen.getByRole("table", {
      name: /3 jurisdictions with changes/,
    });
    const names = () =>
      within(table)
        .getAllByRole("rowheader")
        .map((h) => h.textContent);
    expect(names()).toEqual(["Germany", "European Union", "France"]); // last change, newest first
    expect(
      within(table).getByRole("columnheader", { name: /Last change/ }),
    ).toHaveAttribute("aria-sort", "descending");
    await userEvent.click(
      within(table).getByRole("button", { name: /Items changed/ }),
    );
    expect(names()).toEqual(["Germany", "European Union", "France"]); // most first
    await userEvent.click(
      within(table).getByRole("button", { name: /Items changed/ }),
    );
    expect(names()).toEqual(["France", "European Union", "Germany"]); // then fewest first
    await userEvent.click(
      within(table).getByRole("button", { name: "France" }),
    );
    expect(
      await screen.findByRole("complementary", { name: "France" }),
    ).toBeInTheDocument();
  });

  it("shades the member countries in the region view", async () => {
    fakeApi({
      "GET /auth/me": [
        200,
        { ...ADMIN, permissions: ["items.read", "taxonomy.read"] },
      ],
      "GET /taxonomy/facets": [200, []],
      "GET /jurisdictions/regions": [
        200,
        [
          {
            code: "155",
            name: "Western Europe",
            jurisdiction_codes: ["DE", "FR"],
          },
        ],
      ],
      "GET /map/activity": [
        200,
        {
          ...ACTIVITY,
          view_by: "region",
          rows: [
            {
              code: "155",
              count: 4,
              last_changed_at: "2026-11-18T09:00:00Z",
              max_severity: "major",
            },
          ],
        },
      ],
    });
    renderAt("/");
    const view = await screen.findByLabelText("View");
    await within(view).findByRole("option", { name: "Region" });
    await userEvent.selectOptions(view, "region");
    const map = await engine();
    await waitFor(() => {
      expect(map.steps.get("DE")).toBe(4);
    });
    expect(map.steps.get("FR")).toBe(4);
    const list = await screen.findByRole("listbox", {
      name: /Regions with changes/,
    });
    expect(within(list).getByRole("option")).toHaveTextContent(
      "Western Europe",
    );
    map.on.onSelect("FR");
    expect(
      await screen.findByRole("complementary", { name: "Western Europe" }),
    ).toBeInTheDocument();
  });

  it("opens with the user's landing view (M9 Defaults)", async () => {
    const id = "0190a000-0000-7000-8000-0000000000d1";
    const api = fakeApi({
      "GET /auth/me": [
        200,
        { ...ADMIN, permissions: ["items.read", "taxonomy.read"] },
      ],
      "GET /me/preferences": [
        200,
        { landing_view_id: id, session_idle_timeout_minutes: 480 },
      ],
      "GET /views": [
        200,
        [
          {
            id,
            name: "EU finance",
            view_by: "region",
            period_days: 90,
            color_scheme: "severity",
            filters: { terms: { industry: ["finance"] } },
            shared: false,
          },
        ],
      ],
      "GET /taxonomy/facets": [
        200,
        [
          {
            key: "industry",
            label: "Industry",
            show_in_view_selector: true,
            terms: [
              {
                id: "t1",
                facet_key: "industry",
                key: "finance",
                label: "Finance",
                active: true,
                children: [],
              },
            ],
          },
        ],
      ],
      "GET /jurisdictions/regions": [
        200,
        [{ code: "155", name: "Western Europe", jurisdiction_codes: ["DE"] }],
      ],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    await waitFor(() => {
      const urls = api.fetch.mock.calls
        .map(([r]) => new URL(r.url))
        .filter((u) => u.pathname.endsWith("/map/activity"));
      expect(
        urls.some(
          (u) =>
            u.searchParams.get("period_days") === "90" &&
            u.searchParams.get("view_by") === "region" &&
            u.searchParams.get("filters") ===
              JSON.stringify({ terms: { industry: ["finance"] } }),
        ),
      ).toBe(true);
    });
    expect(screen.getByLabelText("Colour by")).toHaveValue("severity");
  });

  it("ignores landing-view filters this user's View select cannot show", async () => {
    const id = "0190a000-0000-7000-8000-0000000000d2";
    const api = fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["items.read"] }],
      "GET /me/preferences": [
        200,
        { landing_view_id: id, session_idle_timeout_minutes: 480 },
      ],
      "GET /views": [
        200,
        [
          {
            id,
            name: "Shared",
            view_by: "region",
            period_days: 7,
            color_scheme: "count",
            filters: { terms: { industry: ["finance"] } },
            shared: true,
          },
        ],
      ],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    await waitFor(() => {
      const urls = api.fetch.mock.calls
        .map(([r]) => new URL(r.url))
        .filter((u) => u.pathname.endsWith("/map/activity"));
      expect(urls.some((u) => u.searchParams.get("period_days") === "7")).toBe(
        true,
      );
    });
    const urls = api.fetch.mock.calls
      .map(([r]) => new URL(r.url))
      .filter((u) => u.pathname.endsWith("/map/activity"));
    expect(
      urls.every(
        (u) =>
          u.searchParams.get("view_by") === "country" &&
          !u.searchParams.has("filters"),
      ),
    ).toBe(true);
    expect(screen.getByLabelText("View")).toHaveValue("country");
  });

  it("shows live changes: the activity is asked again every minute (G3)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let rows = ACTIVITY.rows.slice(0, 1);
      const api = fakeApi({
        "GET /auth/me": [200, ADMIN],
        "GET /map/activity": () => [200, { ...ACTIVITY, rows }],
      });
      renderAt("/");
      expect(
        await screen.findByText(
          "1 jurisdiction with changes in the last 30 days",
        ),
      ).toBeInTheDocument();
      expect(screen.getByText(/refreshed every minute/)).toBeInTheDocument();
      rows = ACTIVITY.rows;
      const before = api.calls.filter(
        (c) => c.key === "GET /map/activity",
      ).length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(61_000);
      });
      expect(
        await screen.findByText(
          "3 jurisdictions with changes in the last 30 days",
        ),
      ).toBeInTheDocument();
      expect(
        api.calls.filter((c) => c.key === "GET /map/activity").length,
      ).toBeGreaterThan(before);
    } finally {
      vi.useRealTimers();
    }
  });

  it("names no country over a disputed area", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    const map = await engine();
    act(() => {
      map.on.onHover({
        code: "",
        name: "",
        x: 5,
        y: 5,
        note: "Admin. by India; Claimed by China",
        disputed: true,
      });
    });
    expect(await screen.findByText("Disputed area")).toBeInTheDocument();
    expect(
      screen.getByText("Admin. by India; Claimed by China"),
    ).toBeInTheDocument();
    expect(screen.queryByText("India")).toBeNull();
    act(() => {
      map.on.onHover({ code: "DE", name: "Germany", x: 5, y: 5 });
    });
    expect(await screen.findAllByText(/3 items changed/)).toHaveLength(2); // list and tooltip
  });

  it("announces the selection and keeps the list on it", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /map/activity": [200, ACTIVITY],
    });
    renderAt("/");
    const list = await screen.findByRole("listbox");
    const map = await engine();
    map.on.onSelect("FR");
    expect(
      await screen.findByText(/Selected: France, 1 item changed/),
    ).toHaveAttribute("role", "status");
    const options = within(list).getAllByRole("option");
    expect(list).toHaveAttribute("aria-activedescendant", options[2]?.id);
  });

  it("says when the activity cannot be loaded, and refuses users without items.read", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /map/activity": [503, problem(503, "busy")],
    });
    renderAt("/");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    vi.unstubAllGlobals();
    fakeApi({ "GET /auth/me": [200, { ...ADMIN, permissions: [] }] });
    renderAt("/");
    expect(
      (await screen.findAllByText(/do not have permission/)).length,
    ).toBeGreaterThan(0);
  });
});
