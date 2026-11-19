/** Display names of jurisdiction codes, without the taxonomy (which needs `taxonomy.read`). */
const names = new Intl.DisplayNames(["en"], {
  type: "region",
  fallback: "code",
});
const SUPRANATIONAL: Record<string, string> = {
  EU: "European Union",
  COE: "Council of Europe",
  OECD: "OECD",
  UN: "United Nations",
  INTL: "International",
};
export function jurisdictionName(code: string): string {
  if (Object.hasOwn(SUPRANATIONAL, code)) return SUPRANATIONAL[code] ?? code;
  try {
    return /^[A-Z]{2}$/.test(code) ? (names.of(code) ?? code) : code;
  } catch {
    return code;
  }
}
