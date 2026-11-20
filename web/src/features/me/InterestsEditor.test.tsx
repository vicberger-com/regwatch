import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

const OPTIONS = {
  facets: [
    {
      key: "topic",
      label: "Topic",
      terms: [
        { key: "supply-chain", label: "Supply chain security" },
        { key: "ai", label: "AI governance" },
      ],
    },
  ],
  jurisdictions: [
    { code: "CN", name: "China", region_code: "030" },
    { code: "DE", name: "Germany", region_code: "155" },
  ],
  regions: [
    { key: "150", label: "Europe", members: ["DE", "EU", "FR"] },
    { key: "142", label: "Asia", members: ["CN"] },
  ],
};
const INTERESTS = {
  jurisdictions: [],
  regions: ["150"],
  terms: { topic: ["supply-chain"] },
};
const ACTIVITY = {
  period_start: "2026-10-20T00:00:00Z",
  period_end: "2026-11-19T00:00:00Z",
  view_by: "country",
  rows: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("my interests (M11.1)", () => {
  it("picks regions, jurisdictions and topics and saves them", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /me/preferences": [
        200,
        {
          session_idle_timeout_minutes: 480,
          interests: { jurisdictions: [], regions: [], terms: {} },
        },
      ],
      "GET /me/interest-options": [200, OPTIONS],
      "PATCH /me/preferences": (body) => [
        200,
        { session_idle_timeout_minutes: 480, ...(body as object) },
      ],
      "GET /me/sessions": [200, []],
      "GET /views": [200, []],
    });
    renderAt("/me");
    const form = await screen.findByRole("form", { name: "My interests" });
    await userEvent.click(
      within(form).getByRole("checkbox", { name: "Europe" }),
    );
    await userEvent.type(
      within(form).getByRole("searchbox", { name: "Find" }),
      "chi",
    );
    expect(
      within(form).queryByRole("checkbox", { name: "Germany" }),
    ).toBeNull();
    await userEvent.click(
      within(form).getByRole("checkbox", { name: "China" }),
    );
    await userEvent.click(
      within(form).getByRole("checkbox", { name: "AI governance" }),
    );
    await userEvent.click(
      within(form).getByRole("button", { name: "Save my interests" }),
    );
    await waitFor(() => {
      expect(
        api.calls.find((c) => c.key === "PATCH /me/preferences")?.body,
      ).toEqual({
        interests: {
          jurisdictions: ["CN"],
          regions: ["150"],
          terms: { topic: ["ai"] },
        },
      });
    });
    expect(await within(form).findByText("Saved: 3 chosen.")).toHaveAttribute(
      "role",
      "status",
    );
  });

  it("filters the map by default and widens it on request", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /me/preferences": [
        200,
        { session_idle_timeout_minutes: 480, interests: INTERESTS },
      ],
      "GET /map/activity": [200, ACTIVITY],
      "GET /me/interest-options": [200, OPTIONS],
    });
    renderAt("/");
    const filters = () =>
      api.fetch.mock.calls
        .map(([r]) => new URL(r.url))
        .filter((u) => u.pathname.endsWith("/map/activity"))
        .map((u) => u.searchParams.get("filters"));
    await waitFor(() => {
      expect(filters()).toContain(
        JSON.stringify({
          jurisdictions: ["DE", "EU", "FR"],
          terms: { topic: ["supply-chain"] },
        }),
      );
    });
    expect(screen.getByText("Filtered to my interests")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Show everything" }),
    );
    await waitFor(() => {
      expect(filters()).toContain(null);
    });
  });

  it("filters the items list unless the address names its own filters or all", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /me/preferences": [
        200,
        { session_idle_timeout_minutes: 480, interests: INTERESTS },
      ],
      "POST /search": [200, { items: [], total: 0, page: 1, page_size: 25 }],
      "GET /me/interest-options": [200, OPTIONS],
    });
    renderAt("/items");
    await waitFor(() => {
      expect(
        (api.calls.at(-1)?.body as { filters?: object } | undefined)?.filters,
      ).toEqual({
        jurisdictions: ["DE", "EU", "FR"],
        terms: { topic: ["supply-chain"] },
      });
    });
    await userEvent.click(
      await screen.findByRole("button", { name: "Show everything" }),
    );
    await waitFor(() => {
      expect(
        (
          api.calls.filter((c) => c.key === "POST /search").at(-1)?.body as {
            filters?: object;
          }
        ).filters,
      ).toEqual({});
    });
    expect(screen.getByText("Showing everything")).toBeInTheDocument();
  });
});
