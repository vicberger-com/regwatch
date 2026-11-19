import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

import { parseDiff } from "./DiffView";

const ID = "0190a000-0000-7000-8000-0000000000a1";
const ITEM = {
  id: ID,
  title: "NIS2 Umsetzung",
  source_id: "0190a000-0000-7000-8000-0000000000b1",
  last_changed_at: "2026-11-18T09:00:00Z",
  status: "updated",
  jurisdictions: [{ code: "DE" }],
  summary: "Pflichten",
  content_text: "Erster Satz.\nZweiter Satz.",
  content_text_en: "First sentence.\nSecond sentence.",
  current_version_no: 3,
  terms: [
    {
      facet_key: "topic",
      key: "incident",
      label: "Incident reporting",
      confidence: 0.9,
    },
  ],
};
const DIFF =
  "--- v2\n+++ v3\n@@ -1,2 +1,2 @@\n Erster Satz.\n-Zweiter Satz.\n+Zweiter Satz, <b>neu</b>.\n";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("diff parsing", () => {
  it("drops file headers and keeps hunks, additions, removals and context", () => {
    expect(parseDiff(DIFF)).toEqual([
      { kind: "hunk", text: "@@ -1,2 +1,2 @@" },
      { kind: "context", text: "Erster Satz." },
      { kind: "remove", text: "Zweiter Satz." },
      { kind: "add", text: "Zweiter Satz, <b>neu</b>." },
    ]);
    expect(parseDiff("")).toEqual([]);
  });

  it("keeps changed lines that start with dashes or pluses, and marks a cut diff", () => {
    const tricky =
      "--- previous\r\n+++ current\r\n@@ -1,2 +1,2 @@\r\n----\r\n+++x\r\n--- signature\r\n... (diff cut at 64 KB)";
    expect(parseDiff(tricky)).toEqual([
      { kind: "hunk", text: "@@ -1,2 +1,2 @@" },
      { kind: "remove", text: "---" },
      { kind: "add", text: "++x" },
      { kind: "remove", text: "-- signature" },
      { kind: "cut", text: "The diff was cut at 64 KB." },
    ]);
  });
});

describe("item tabs", () => {
  it("offers only versions that exist, and asks for a diff once, on Compare", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      [`GET /items/${ID}`]: [200, { ...ITEM, current_version_no: 9 }],
      [`GET /items/${ID}/versions`]: [
        200,
        [{ version_no: 2 }, { version_no: 5 }, { version_no: 9 }],
      ],
      [`GET /items/${ID}/diff`]: [200, { unified_diff: DIFF }],
    });
    renderAt(`/items/${ID}`);
    await userEvent.click(await screen.findByRole("tab", { name: "Versions" }));
    expect(
      await screen.findByRole("button", { name: "Compare with version 5" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Diff" }));
    const from = await screen.findByLabelText("From version");
    expect(
      within(from)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["9", "5", "2"]);
    const diffs = () =>
      api.calls.filter((c) => c.key === `GET /items/${ID}/diff`).length;
    await waitFor(() => {
      expect(diffs()).toBe(1); // 5 to 9 by default
    });
    await userEvent.selectOptions(from, "2");
    await userEvent.selectOptions(screen.getByLabelText("To version"), "5");
    expect(diffs()).toBe(1); // nothing until Compare
    await userEvent.click(screen.getByRole("button", { name: "Compare" }));
    await waitFor(() => {
      expect(diffs()).toBe(2);
    });
  });

  it("moves between tabs by keyboard and shows tags, content and its translation", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      [`GET /items/${ID}`]: [200, ITEM],
    });
    renderAt(`/items/${ID}`);
    const summary = await screen.findByRole("tab", { name: "Summary" });
    expect(summary).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent(
      "Incident reporting · 90%",
    );
    summary.focus();
    await userEvent.keyboard("{ArrowRight}");
    const content = screen.getByRole("tab", { name: "Content" });
    expect(content).toHaveFocus();
    expect(content).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Erster Satz.");
    await userEvent.click(
      screen.getByLabelText("Show the English translation"),
    );
    expect(screen.getByRole("tabpanel")).toHaveTextContent("First sentence.");
    screen.getByRole("tab", { name: "Content" }).focus();
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Diff" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("compares a version with the one before, as text with markers", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      [`GET /items/${ID}`]: [200, ITEM],
      [`GET /items/${ID}/versions`]: [
        200,
        [
          { version_no: 1, created_at: "2026-11-01T00:00:00Z" },
          {
            version_no: 2,
            created_at: "2026-11-10T00:00:00Z",
            changed_pct: 12.5,
          },
          { version_no: 3, created_at: "2026-11-18T00:00:00Z", changed_pct: 3 },
        ],
      ],
      [`GET /items/${ID}/diff`]: [
        200,
        { from_version: 2, to_version: 3, unified_diff: DIFF },
      ],
    });
    renderAt(`/items/${ID}`);
    await userEvent.click(await screen.findByRole("tab", { name: "Versions" }));
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("3");
    await userEvent.click(
      within(table).getByRole("button", { name: "Compare with version 2" }),
    );
    expect(screen.getByRole("tab", { name: "Diff" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const figure = await screen.findByRole("figure");
    expect(figure).toHaveTextContent(
      "Version 2 to 3: 1 lines added, 1 removed",
    );
    expect(
      within(figure).getByText("Removed:", { exact: false }),
    ).toBeInTheDocument();
    expect(figure.querySelector("b")).toBeNull(); // captured markup stays text
    expect(figure).toHaveTextContent("Zweiter Satz, <b>neu</b>.");
    await waitFor(() => {
      const asked = api.fetch.mock.calls.map(([r]) => new URL(r.url).search);
      expect(asked).toContain("?from=2&to=3");
    });
  });

  it("says there is nothing to compare for a single version", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      [`GET /items/${ID}`]: [200, { ...ITEM, current_version_no: 1 }],
      [`GET /items/${ID}/versions`]: [200, [{ version_no: 1 }]],
    });
    renderAt(`/items/${ID}`);
    await userEvent.click(await screen.findByRole("tab", { name: "Diff" }));
    expect(await screen.findByText(/nothing to compare/)).toBeInTheDocument();
  });
});
