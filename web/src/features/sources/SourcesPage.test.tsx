import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem, type Routes } from "@/test/api";
import { renderAt } from "@/test/render";

const READER = { ...ADMIN, permissions: ["sources.read"] };
const EDITOR = { ...ADMIN, permissions: ["sources.read", "sources.manage"] };
const OWNER = {
  ...ADMIN,
  permissions: ["sources.read", "sources.manage", "sources.override_robots"],
};
const JOB = {
  id: "j1",
  source_id: "s1",
  cron: null,
  interval_seconds: 1800,
  timezone: "UTC",
  max_items_per_run: 200,
  rate_limit_per_minute: 30,
  enabled: true,
  next_run_at: "2026-11-17T10:30:00Z",
  last_run_at: "2026-11-17T10:00:00Z",
};
const SOURCE = {
  id: "s1",
  name: "EU feed",
  kind: "rss",
  config: { feed_url: "https://feeds.example/rss" },
  credibility: "official",
  robots_policy: "respect",
  enabled: true,
  health: "degraded",
  consecutive_failures: 1,
  job: JOB,
};
const PAGE = { items: [SOURCE], total: 1, page: 1, page_size: 50 };
const RUNS = {
  items: [
    {
      id: "r2",
      job_id: "j1",
      started_at: "2026-11-17T10:00:00Z",
      status: "failed",
      items_new: 0,
      bytes_fetched: 412,
      error_class: "unsafe-feed",
      error_message: "the feed has a DOCTYPE",
      robots_decision: "allowed",
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
};
const HEALTH = {
  source_id: "s1",
  health: "degraded",
  consecutive_failures: 1,
  success_rate_7d: 0.5,
  runs_7d: 2,
  last_error: "unsafe-feed: the feed has a DOCTYPE",
};
const BASE = {
  "GET /sources": [200, PAGE],
  "GET /capture-runs": [200, RUNS],
  "GET /sources/s1/health": [200, HEALTH],
} satisfies Routes;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sources screen", () => {
  it("lists sources read-only for readers, with health and the reason a run failed", async () => {
    fakeApi({ "GET /auth/me": [200, READER], ...BASE });
    renderAt("/admin/sources");
    const table = await screen.findByRole("table", {
      name: /Sources, 1 in all/,
    });
    expect(within(table).getByText("EU feed")).toBeInTheDocument();
    expect(within(table).getByText("degraded")).toBeInTheDocument();
    expect(within(table).getByText("2026-11-17 10:30 UTC")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create source" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit EU feed" })).toBeNull();

    await userEvent.click(
      screen.getByRole("button", { name: "Runs and health of EU feed" }),
    );
    expect(
      await screen.findByText(/2 runs in 7 days · 50% succeeded/),
    ).toBeInTheDocument();
    const runs = await screen.findByRole("table", {
      name: "Runs, newest first",
    });
    expect(within(runs).getByText("unsafe-feed")).toBeInTheDocument();
    expect(within(runs).getByText(/refused for safety/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run now" })).toBeNull();
  });

  it("creates an RSS source from the generated form, without robots fields for editors", async () => {
    const { calls } = fakeApi({
      "GET /auth/me": [200, EDITOR],
      ...BASE,
      "POST /sources": [201, SOURCE],
    });
    renderAt("/admin/sources");
    await userEvent.click(
      await screen.findByRole("button", { name: "Create source" }),
    );
    const form = screen.getByRole("form", { name: "Create source" });
    await userEvent.type(within(form).getByLabelText("Name"), "New feed");
    await userEvent.type(
      within(form).getByLabelText(/Feed url/),
      "https://feeds.example/new",
    );
    expect(within(form).queryByText(/Override robots.txt/)).toBeNull();
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => {
      expect(calls.some((c) => c.key === "POST /sources")).toBe(true);
    });
    const body = calls.find((c) => c.key === "POST /sources")?.body as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({
      name: "New feed",
      kind: "rss",
      config: {
        feed_url: "https://feeds.example/new",
        fetch_full_page: true,
        etag_conditional: true,
        max_entries: 100,
      },
      job: { interval_seconds: 3600, cron: null, rate_limit_per_minute: 30 },
    });
    expect(body).not.toHaveProperty("robots_policy");
  });

  it("lets override holders override robots.txt with a reason", async () => {
    const { calls } = fakeApi({
      "GET /auth/me": [200, OWNER],
      ...BASE,
      "PATCH /sources/s1": [200, SOURCE],
    });
    renderAt("/admin/sources");
    await userEvent.click(
      await screen.findByRole("button", { name: "Edit EU feed" }),
    );
    const form = screen.getByRole("form", { name: "Edit source EU feed" });
    expect(within(form).getByLabelText("Kind")).toBeDisabled();
    await userEvent.click(within(form).getByLabelText(/Override robots.txt/));
    await userEvent.type(
      within(form).getByLabelText(/Reason/),
      "Owner agreed in writing",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => {
      expect(calls.some((c) => c.key === "PATCH /sources/s1")).toBe(true);
    });
    const body = calls.find((c) => c.key === "PATCH /sources/s1")
      ?.body as Record<string, unknown>;
    expect(body).toMatchObject({
      robots_policy: "override",
      override_reason: "Owner agreed in writing",
      job: { interval_seconds: 1800 },
    });
    expect(body).not.toHaveProperty("kind");
  });

  it("shows the field the API refused", async () => {
    fakeApi({
      "GET /auth/me": [200, EDITOR],
      ...BASE,
      "POST /sources": [
        422,
        {
          ...problem(422),
          errors: [
            {
              field: "config.feed_url",
              message: "the host must resolve to public addresses only",
            },
          ],
        },
      ],
    });
    renderAt("/admin/sources");
    await userEvent.click(
      await screen.findByRole("button", { name: "Create source" }),
    );
    const form = screen.getByRole("form", { name: "Create source" });
    await userEvent.type(within(form).getByLabelText("Name"), "Bad");
    await userEvent.type(
      within(form).getByLabelText(/Feed url/),
      "http://10.0.0.5/x",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "config.feed_url: the host must resolve to public addresses only",
    );
  });

  it("queues a run and disables a source", async () => {
    const { calls } = fakeApi({
      "GET /auth/me": [200, EDITOR],
      ...BASE,
      "POST /capture-jobs/j1/run-now": [202, { id: "r3", status: "running" }],
      "DELETE /sources/s1": [204, undefined],
    });
    renderAt("/admin/sources");
    await userEvent.click(
      await screen.findByRole("button", { name: "Runs and health of EU feed" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Run now" }),
    );
    expect(await screen.findByText("Run queued.")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Disable source" }),
    );
    await vi.waitFor(() => {
      expect(calls.some((c) => c.key === "DELETE /sources/s1")).toBe(true);
    });
  });
});
