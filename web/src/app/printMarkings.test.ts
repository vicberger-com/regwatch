import { afterEach, describe, expect, it } from "vitest";

import { applyPrintMarkings, cssText, printRule } from "./printMarkings";

afterEach(() => {
  document.getElementById("regwatch-print-markings")?.remove();
});

describe("markings on every printed page (M8.5)", () => {
  it("escapes everything that could end the CSS string or rule", () => {
    expect(cssText("INTERNAL USE")).toBe("INTERNAL USE");
    const hostile = 'x"; } body { display: none } @page { content: "';
    const escaped = cssText(hostile);
    expect(escaped).not.toMatch(/["{};:@]/);
    expect(escaped).toContain("\\000022 "); // the quote, as a hex escape
    expect(cssText("Ünter\nline")).toBe("\\0000dc nter\\00000a line");
  });

  it("puts the markings and page numbers in the page margin, and updates one style", () => {
    expect(printRule("INTERNAL USE")).toContain(
      '@bottom-left { content: "INTERNAL USE"',
    );
    expect(printRule("")).not.toContain("@bottom-left");
    expect(printRule(null)).toContain('counter(page) " of " counter(pages)');
    applyPrintMarkings("ONE");
    applyPrintMarkings("TWO");
    const styles = document.querySelectorAll("#regwatch-print-markings");
    expect(styles).toHaveLength(1);
    expect(styles[0]?.textContent).toContain('"TWO"');
  });
});
