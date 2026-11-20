import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

const EDITOR = { ...ADMIN, permissions: ["sources.read", "sources.manage"] };
const REQ = {
  id: "0190a000-0000-7000-8000-0000000000a1",
  created_at: "2026-11-20T10:00:00Z",
  url: "https://xn--gv-fmc.uk/feed",
  reason: "Our regulator.",
  status: "pending",
  requested_by: "Vic",
};
const SOURCE = {
  id: "s1",
  name: "UK feed",
  kind: "rss",
  robots_policy: "respect",
  enabled: true,
  health: "unknown",
  catalogue_key: null,
};
const CRAWL = { ...SOURCE, id: "s2", name: "Crawler", kind: "web_crawl" };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("feed requests (M11.3)", () => {
  it("lets a user ask for a feed and withdraw it", async () => {
    const mine: object[] = [];
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /me/sessions": [200, []],
      "GET /views": [200, []],
      "GET /feed-requests": () => [200, mine],
      "POST /feed-requests": (body) => {
        mine.push({ ...REQ, ...(body as object), requested_by: null });
        return [201, mine[0]];
      },
      [`DELETE /feed-requests/${REQ.id}`]: () => {
        mine[0] = { ...mine[0], status: "withdrawn" };
        return [204, undefined];
      },
    });
    renderAt("/me");
    const form = await screen.findByRole("form", { name: "Ask for a feed" });
    await userEvent.type(
      within(form).getByLabelText("Feed or page address (https)"),
      "https://example.org/feed.xml",
    );
    await userEvent.type(
      within(form).getByLabelText("Why it matters"),
      "Notices.",
    );
    await userEvent.click(
      within(form).getByRole("button", { name: "Send the request" }),
    );
    expect(await within(form).findByRole("status")).toHaveTextContent("Sent");
    expect(
      api.calls.find((c) => c.key === "POST /feed-requests")?.body,
    ).toEqual({ url: "https://example.org/feed.xml", reason: "Notices." });
    const list = await screen.findByRole("list", { name: "Your requests" });
    expect(within(list).getByText("Waiting for an editor")).toBeVisible();
    await userEvent.click(
      within(list).getByRole("button", { name: /Withdraw the request/ }),
    );
    expect(await within(list).findByText("Withdrawn")).toBeVisible();
  });

  it("shows editors the real host and approves with a catalogue-kind source", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, EDITOR],
      "GET /sources": [
        200,
        { items: [SOURCE, CRAWL], total: 2, page: 1, page_size: 50 },
      ],
      "GET /feed-requests": [200, [REQ]],
      [`POST /feed-requests/${REQ.id}/decision`]: (body) => [
        200,
        { ...REQ, ...(body as object), status: "approved" },
      ],
    });
    renderAt("/admin/sources");
    const queue = await screen.findByRole("region", {
      name: /Feed requests \(1 waiting\)/,
    });
    expect(within(queue).getByText("xn--gv-fmc.uk")).toBeVisible();
    expect(within(queue).queryByRole("link")).toBeNull(); // never a link to it
    const picker = within(queue).getByLabelText(/Source created for it/);
    expect(
      within(picker).queryByRole("option", { name: "Crawler" }),
    ).toBeNull();
    await userEvent.selectOptions(picker, "s1");
    expect(within(queue).getByText(/rss · robots.txt: respect/)).toBeVisible();
    await userEvent.type(
      within(queue).getByLabelText("One line for the catalogue"),
      "UK notices.",
    );
    await userEvent.click(
      within(queue).getByRole("button", { name: /Approve the request/ }),
    );
    await waitFor(() => {
      expect(api.calls.find((c) => c.key.endsWith("/decision"))?.body).toEqual({
        decision: "approved",
        source_id: "s1",
        summary: "UK notices.",
        note: null,
      });
    });
  });

  it("hides the queue from those who cannot manage sources", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["sources.read"] }],
      "GET /sources": [200, { items: [], total: 0, page: 1, page_size: 50 }],
    });
    renderAt("/admin/sources");
    await screen.findByRole("heading", { name: "Sources" });
    expect(screen.queryByRole("region", { name: /Feed requests/ })).toBeNull();
  });
});
