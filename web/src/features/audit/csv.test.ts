import { describe, expect, it } from "vitest";

import { csvField, toCsv } from "./csv";

describe("audit CSV", () => {
  it("quotes every field and doubles quotes", () => {
    expect(csvField('say "hi", ok')).toBe('"say ""hi"", ok"');
    expect(csvField(null)).toBe('""');
    expect(csvField({ a: 1 })).toBe('"{""a"":1}"');
  });

  it("defuses values a spreadsheet would run as formulas", () => {
    for (const v of ["=1+1", "+SUM(A1)", "-2", "@cmd", "\tx", "\rx"]) {
      expect(csvField(v).startsWith(`"'`)).toBe(true);
    }
    expect(csvField("plain")).toBe('"plain"');
  });

  it("writes a header and one CRLF line per entry", () => {
    const csv = toCsv([
      { id: "1", action: "role.update", actor_email: "=evil()" },
    ]);
    const lines = csv.split("\r\n");
    expect(lines[0]).toMatch(/^occurred_at,actor_email,/);
    expect(lines[1]).toContain(`"'=evil()"`);
    expect(lines).toHaveLength(3); // header, row, trailing empty
  });
});
