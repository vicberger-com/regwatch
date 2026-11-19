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
