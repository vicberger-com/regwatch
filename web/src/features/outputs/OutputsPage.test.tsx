import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

const ANALYST = {
  ...ADMIN,
  permissions: ["outputs.pdf", "outputs.csv", "outputs.schedule", "items.read"],
};
const JOB = {
  id: "j1",
  kind: "pdf",
  status: "sent",
  requested_by: ADMIN.id,
  source_summary: "stock report source-health",
  destination_summary: "download",
  artifact_available: true,
  created_at: "2026-11-20T09:00:00Z",
};
const FAILED = {
  ...JOB,
  id: "j2",
  kind: "csv",
  status: "failed",
  artifact_available: false,
  source_summary: "query",
  error_class: "forbidden",
  error_message: "CSV exports need outputs.csv.",
};
const OTHERS = {
  ...JOB,
  id: "j3",
  requested_by: "someone",
  status: "queued",
  artifact_available: false,
};
const SCHEDULE = {
  ...JOB,
  id: "s1",
  status: "failed",
  artifact_available: false,
  scheduled_cron: "0 7 * * 1",
  next_run_at: null,
  error_class: "source-deleted",
};
const page = (items: unknown[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 25,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("outputs (M8.6)", () => {
  it("lists the history with downloads; only one's own can be retried or cancelled", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ANALYST],
      "GET /outputs": (_b, url) => [
        200,
        page(
          url.searchParams.get("scheduled") === "true"
            ? []
            : [JOB, FAILED, OTHERS],
        ),
      ],
      "POST /outputs/j2/retry": [202, { ...FAILED, status: "queued" }],
    });
    renderAt("/outputs");
    const table = await screen.findByRole("table");
    const download = within(table).getByRole("link", {
      name: /^Download PDF of stock report source-health, /,
    });
    expect(download).toHaveAttribute("href", "/api/v1/outputs/j1/artifact");
    expect(
      within(table).getByText("CSV exports need outputs.csv."),
    ).toBeVisible();
    expect(
      within(table).queryByRole("button", { name: /Cancel PDF/ }),
    ).toBeNull(); // the queued job is someone else's
    expect(screen.queryByRole("radio", { name: "Everyone's" })).toBeNull();
    await userEvent.click(
      within(table).getByRole("button", { name: /^Retry CSV of query, / }),
    );
    await waitFor(() => {
      expect(api.calls.map((c) => c.key)).toContain("POST /outputs/j2/retry");
    });
  });

  it("shows schedules with their state, and resumes or removes them", async () => {
    vi.stubGlobal("confirm", () => true);
    const api = fakeApi({
      "GET /auth/me": [200, ANALYST],
      "GET /outputs": (_b, url) => [
        200,
        page(url.searchParams.get("scheduled") === "true" ? [SCHEDULE] : []),
      ],
      "DELETE /outputs/s1": [204, undefined],
    });
    renderAt("/outputs");
    await screen.findByText("No outputs yet.");
    await userEvent.click(screen.getByRole("tab", { name: "Schedules" }));
    const table = await screen.findByRole("table");
    expect(within(table).getByText("0 7 * * 1")).toBeVisible();
    expect(within(table).getByText("Paused")).toBeVisible();
    expect(
      within(table).getByText("Its report or saved view was deleted."),
    ).toBeVisible();
    expect(
      within(table).getByRole("button", { name: /^Resume PDF/ }),
    ).toBeVisible();
    await userEvent.click(
      within(table).getByRole("button", { name: /^Remove PDF/ }),
    );
    await waitFor(() => {
      expect(api.calls.map((c) => c.key)).toContain("DELETE /outputs/s1");
    });
  });

  it("offers everyone's outputs with outputs.read_all, and reports a failed load", async () => {
    const api = fakeApi({
      "GET /auth/me": [
        200,
        {
          ...ANALYST,
          permissions: [...ANALYST.permissions, "outputs.read_all"],
        },
      ],
      "GET /outputs": (_b, url) =>
        url.searchParams.get("scope") === "all"
          ? [503, problem(503, "The database is not available.")]
          : [200, page([])],
    });
    renderAt("/outputs");
    await screen.findByText("No outputs yet.");
    await userEvent.click(screen.getByRole("radio", { name: "Everyone's" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The database is not available.",
    );
    const lists = api.calls.filter((c) => c.key === "GET /outputs");
    expect(lists.length).toBeGreaterThan(0);
    expect(lists.every((c) => c.passive === "1")).toBe(true); // never renews the session
  });

  it("is not offered without outputs.pdf", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["items.read"] }],
    });
    renderAt("/outputs");
    expect(await screen.findByText(/not permitted|permission/i)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Outputs" })).toBeNull();
  });
});

describe("new output (M8.6b)", () => {
  const EMAILER = {
    ...ADMIN,
    permissions: [
      "outputs.pdf",
      "outputs.email",
      "outputs.schedule",
      "reports.print",
      "items.read",
    ],
  };

  it("emails a stock report on a schedule, and shows the server's refusal", async () => {
    let attempt = 0;
    const api = fakeApi({
      "GET /auth/me": [200, EMAILER],
      "GET /outputs": [200, page([])],
      "GET /reports/templates": [
        200,
        [{ key: "source-health", label: "Source health", version: 1 }],
      ],
      "POST /outputs": () => {
        attempt += 1;
        return attempt === 1
          ? [
              422,
              {
                ...problem(422),
                errors: [
                  {
                    field: "destination.emails",
                    message: "kim@evil.example is not on an allowed domain",
                  },
                ],
              },
            ]
          : [
              202,
              {
                ...SCHEDULE,
                status: "queued",
                next_run_at: "2026-11-23T06:00:00Z",
              },
            ];
      },
    });
    renderAt("/outputs");
    await userEvent.click(
      await screen.findByRole("button", { name: "New output" }),
    );
    const form = screen.getByRole("form", { name: "New output" });
    // Only what this user may use: no CSV without outputs.csv.
    const what = within(form).getByRole("combobox", { name: "What" });
    expect(
      within(what).queryByRole("option", { name: "CSV export" }),
    ).toBeNull();
    await userEvent.selectOptions(what, "email");
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "Report" }),
      await within(form).findByRole("option", { name: "Source health" }),
    );
    await userEvent.type(
      within(form).getByRole("textbox", {
        name: "Recipients, one address a line",
      }),
      "kim@evil.example",
    );
    // More than the server's 20 recipients is caught before sending (M8.6b review).
    const box = within(form).getByRole("textbox", {
      name: "Recipients, one address a line",
    });
    await userEvent.type(
      box,
      Array.from({ length: 21 }, (_, n) => `\na${String(n)}@example.org`).join(
        "",
      ),
    );
    expect(
      within(form).getByText(/At most 20 recipients; this has 22\./),
    ).toBeVisible();
    expect(
      within(form).getByRole("button", { name: "Request" }),
    ).toBeDisabled();
    await userEvent.clear(box);
    await userEvent.type(box, "kim@evil.example");
    await userEvent.click(
      within(form).getByRole("checkbox", { name: /Repeat on a schedule/ }),
    );
    await userEvent.click(
      within(form).getByRole("button", { name: "Schedule" }),
    );
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "kim@evil.example is not on an allowed domain",
    );
    await userEvent.click(
      within(form).getByRole("button", { name: "Schedule" }),
    );
    expect(await within(form).findByRole("status")).toHaveTextContent(
      "Scheduled.",
    );
    const sent = api.calls.filter((c) => c.key === "POST /outputs").at(-1);
    expect(sent?.body).toEqual({
      kind: "email",
      source: { report_template_key: "source-health" },
      destination: { emails: ["kim@evil.example"], copies: 1 },
      schedule: { cron: "0 7 * * 1" },
    });
  });

  it("exports a saved view as CSV", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ANALYST],
      "GET /outputs": [200, page([])],
      "GET /views": [200, [{ id: "v1", name: "EU privacy" }]],
      "POST /outputs": [202, { ...JOB, kind: "csv", status: "queued" }],
    });
    renderAt("/outputs");
    await userEvent.click(
      await screen.findByRole("button", { name: "New output" }),
    );
    const form = screen.getByRole("form", { name: "New output" });
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "What" }),
      "csv",
    );
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "Items" }),
      await within(form).findByRole("option", {
        name: "Saved view: EU privacy",
      }),
    );
    await userEvent.click(
      within(form).getByRole("button", { name: "Request" }),
    );
    expect(await within(form).findByRole("status")).toHaveTextContent(
      "Requested.",
    );
    expect(api.calls.find((c) => c.key === "POST /outputs")?.body).toEqual({
      kind: "csv",
      source: { saved_view_id: "v1" },
    });
  });
});

describe("stock report settings (use testing U-M7-1)", () => {
  it("asks for the jurisdiction of a jurisdiction profile and sends it", async () => {
    const api = fakeApi({
      "GET /auth/me": [
        200,
        {
          ...ADMIN,
          permissions: ["outputs.pdf", "reports.print", "items.read"],
        },
      ],
      "GET /outputs": [200, page([])],
      "GET /reports/templates": [
        200,
        [
          {
            key: "jurisdiction-profile",
            label: "Jurisdiction profile",
            version: 1,
            parameters: [
              {
                key: "jurisdiction",
                label: "Jurisdiction",
                type: "jurisdiction",
                required: true,
              },
              {
                key: "period_days",
                label: "Days covered",
                type: "period_days",
                default: 90,
              },
            ],
          },
        ],
      ],
      "GET /me/interest-options": [
        200,
        {
          facets: [],
          jurisdictions: [{ code: "DE", name: "Germany" }],
          regions: [],
        },
      ],
      "POST /outputs": [202, { ...JOB, status: "queued" }],
    });
    renderAt("/outputs");
    await userEvent.click(
      await screen.findByRole("button", { name: "New output" }),
    );
    const form = screen.getByRole("form", { name: "New output" });
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "Report" }),
      await within(form).findByRole("option", { name: "Jurisdiction profile" }),
    );
    const place = await within(form).findByRole("combobox", {
      name: "Jurisdiction",
    });
    expect(
      within(form).getByRole("button", { name: "Request" }),
    ).toBeDisabled();
    await userEvent.selectOptions(
      place,
      await within(place).findByRole("option", { name: "Germany" }),
    );
    expect(
      within(form).getByRole("combobox", { name: "Days covered (optional)" }),
    ).toHaveValue("90");
    await userEvent.click(
      within(form).getByRole("button", { name: "Request" }),
    );
    await within(form).findByText(/Requested\./);
    expect(api.calls.find((c) => c.key === "POST /outputs")?.body).toEqual({
      kind: "pdf",
      source: { report_template_key: "jurisdiction-profile" },
      params: { period_days: 90, jurisdiction: "DE" },
    });
  });
});

describe("New output from the Reports page (U-M7-2)", () => {
  it("opens with the chosen stock report", async () => {
    fakeApi({
      "GET /auth/me": [
        200,
        { ...ADMIN, permissions: ["outputs.pdf", "reports.print"] },
      ],
      "GET /outputs": [200, page([])],
      "GET /reports/templates": [
        200,
        [{ key: "source-health", label: "Source health" }],
      ],
    });
    renderAt("/outputs?new=t:source-health");
    const form = await screen.findByRole("form", { name: "New output" });
    await waitFor(() => {
      expect(
        within(form).getByRole("combobox", { name: "Report" }),
      ).toHaveValue("t:source-health");
    });
  });
});

describe("network printing in New output (M8.5b)", () => {
  it("sends a report to a chosen printer with its copies", async () => {
    const api = fakeApi({
      "GET /auth/me": [
        200,
        {
          ...ADMIN,
          permissions: ["outputs.pdf", "outputs.print", "reports.print"],
        },
      ],
      "GET /outputs": [200, page([])],
      "GET /reports/templates": [
        200,
        [{ key: "source-health", label: "Source health" }],
      ],
      "GET /printers": [200, [{ id: "p1", name: "Floor 2" }]],
      "POST /outputs": [202, { ...JOB, kind: "print", status: "queued" }],
    });
    renderAt("/outputs");
    await userEvent.click(
      await screen.findByRole("button", { name: "New output" }),
    );
    const form = screen.getByRole("form", { name: "New output" });
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "What" }),
      "print",
    );
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "Report" }),
      await within(form).findByRole("option", { name: "Source health" }),
    );
    expect(
      within(form).getByRole("button", { name: "Request" }),
    ).toBeDisabled();
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "Printer" }),
      await within(form).findByRole("option", { name: "Floor 2" }),
    );
    const copies = within(form).getByRole("spinbutton", { name: "Copies" });
    await userEvent.clear(copies);
    await userEvent.type(copies, "3");
    await userEvent.click(
      within(form).getByRole("button", { name: "Request" }),
    );
    await within(form).findByText(/Requested\./);
    expect(api.calls.find((c) => c.key === "POST /outputs")?.body).toEqual({
      kind: "print",
      source: { report_template_key: "source-health" },
      destination: { printer_id: "p1", copies: 3 },
    });
  });

  it("says so when server printing is off", async () => {
    fakeApi({
      "GET /auth/me": [
        200,
        { ...ADMIN, permissions: ["outputs.pdf", "outputs.print"] },
      ],
      "GET /outputs": [200, page([])],
      "GET /printers": [404, problem(404)],
    });
    renderAt("/outputs");
    await userEvent.click(
      await screen.findByRole("button", { name: "New output" }),
    );
    const form = screen.getByRole("form", { name: "New output" });
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "What" }),
      "print",
    );
    expect(
      await within(form).findByText(/Printing to network printers is off/),
    ).toBeVisible();
    expect(
      within(form).getByRole("button", { name: "Request" }),
    ).toBeDisabled();
  });
});
