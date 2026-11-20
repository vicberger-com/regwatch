import { afterEach, describe, expect, it } from "vitest";

import { formatDateTime, setTimeZone } from "./format";

afterEach(() => {
  setTimeZone(undefined);
});

describe("dates in the user's time zone (U-M9-1)", () => {
  it("formats in the chosen zone, and ignores one the browser does not know", () => {
    const at = "2026-11-20T23:30:00Z";
    setTimeZone("Asia/Tokyo");
    const tokyo = formatDateTime(at);
    setTimeZone("UTC");
    const utc = formatDateTime(at);
    expect(tokyo).not.toBe(utc); // 08:30 the next day in Tokyo
    expect(tokyo).toMatch(/Nov 21/);
    setTimeZone("Mars/Olympus");
    expect(() => formatDateTime(at)).not.toThrow();
    expect(formatDateTime("not a date")).toBe("—");
  });
});
