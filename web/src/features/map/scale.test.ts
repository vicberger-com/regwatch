import { describe, expect, it } from "vitest";

import { legend, step, steps, type ActivityRow } from "./scale";

const period = {
  start: new Date("2026-10-20T00:00:00Z"),
  end: new Date("2026-11-19T00:00:00Z"),
};
const row = (over: Partial<ActivityRow>): ActivityRow => ({
  code: "DE",
  count: 1,
  last_changed_at: "2026-11-18T00:00:00Z",
  max_severity: "info",
  ...over,
});

describe("map colour steps", () => {
  it("is neutral without changes in the period", () => {
    expect(step(undefined, "recency", period, 5)).toBe(0);
    expect(step(row({ count: 0 }), "count", period, 5)).toBe(0);
  });

  it("darkens with recency by quarter of the period", () => {
    expect(
      step(
        row({ last_changed_at: "2026-11-18T00:00:00Z" }),
        "recency",
        period,
        1,
      ),
    ).toBe(4);
    expect(
      step(
        row({ last_changed_at: "2026-11-05T00:00:00Z" }),
        "recency",
        period,
        1,
      ),
    ).toBe(3);
    expect(
      step(
        row({ last_changed_at: "2026-10-28T00:00:00Z" }),
        "recency",
        period,
        1,
      ),
    ).toBe(2);
    expect(
      step(
        row({ last_changed_at: "2026-10-21T00:00:00Z" }),
        "recency",
        period,
        1,
      ),
    ).toBe(1);
    expect(step(row({ last_changed_at: null }), "recency", period, 1)).toBe(1);
  });

  it("scales counts logarithmically and severities by level", () => {
    const got = steps(
      [row({ code: "A", count: 1 }), row({ code: "B", count: 1000 })],
      "count",
      period,
    );
    expect(got.get("A")).toBe(1);
    expect(got.get("B")).toBe(4);
    expect(step(row({ max_severity: "major" }), "severity", period, 1)).toBe(4);
    expect(step(row({ max_severity: "notable" }), "severity", period, 1)).toBe(
      3,
    );
  });

  it("labels five steps for every encoding", () => {
    for (const e of ["recency", "count", "severity"] as const)
      expect(legend(e)).toHaveLength(5);
  });
});
