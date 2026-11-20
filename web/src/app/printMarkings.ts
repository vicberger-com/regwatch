/**
 * The required markings on every printed page (M8.5 review; CP-08): an `@page` margin box, as
 * the report PDFs carry them (M7), so they never cover the page's content. The text is an
 * administrator's, so it goes into the CSS string escaped as the server's `css_text`: everything
 * but ASCII letters, digits and spaces as a hex escape, so nothing can end the string or rule.
 */
const ID = "regwatch-print-markings";

export function cssText(value: string): string {
  return Array.from(value)
    .map((c) =>
      /^[A-Za-z0-9 ]$/.test(c)
        ? c
        : `\\${(c.codePointAt(0) ?? 0).toString(16).padStart(6, "0")} `,
    )
    .join("");
}

export function printRule(markings: string | null | undefined): string {
  const left = markings?.trim()
    ? ` @bottom-left { content: "${cssText(markings.trim())}"; font-size: 9pt; }`
    : "";
  return `@media print { @page { margin: 14mm 12mm 16mm;${left} @bottom-right { content: "Page " counter(page) " of " counter(pages); font-size: 9pt; } } }`;
}

/** Keep one style element in the head with the current rule. */
export function applyPrintMarkings(markings: string | null | undefined): void {
  let style = document.getElementById(ID);
  if (!style) {
    style = document.createElement("style");
    style.id = ID;
    document.head.appendChild(style);
  }
  style.textContent = printRule(markings); // text, never parsed as HTML
}
