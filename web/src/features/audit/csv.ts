/** CSV export of the audit log (screens.md `/admin/audit`: "CSV export"; use testing U-M1-3). */
import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

type Entry = Schemas["AuditEntry"];
export interface AuditFilters {
  actor?: string;
  action?: string;
  entity_type?: string;
  from?: string;
  to?: string;
}

const PAGE = 200; // the contract's page_size maximum
export const MAX_EXPORT_ROWS = 10_000;
const COLUMNS = [
  "id", "occurred_at", "actor_email", "actor_user_id", "action", "entity_type", "entity_id",
  "ip", "request_id", "before", "after",
] as const; // prettier-ignore

/**
 * One CSV field. A value that a spreadsheet would read as a formula (starting with =, +, -, @,
 * tab or carriage return) gets a leading apostrophe, so opening the file runs nothing (CSV
 * injection, 7.7); every field is quoted, with quotes doubled (RFC 4180).
 */
export function csvField(value: unknown): string {
  let text =
    value === null || value === undefined
      ? ""
      : typeof value === "string"
        ? value
        : JSON.stringify(value);
  // Also after leading whitespace, and for the full-width signs some spreadsheets accept.
  if (
    /^[\s]*[=+\-@\uFF1D\uFF0B\uFF0D\uFF20]/.test(text) ||
    /^[\t\r\n]/.test(text)
  )
    text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

export function toCsv(entries: Entry[]): string {
  const lines = [COLUMNS.join(",")];
  for (const e of entries)
    lines.push(COLUMNS.map((c) => csvField(e[c])).join(","));
  return lines.join("\r\n") + "\r\n";
}

/** Every entry matching the filters, newest first as the API orders them, up to the cap. */
export async function fetchForExport(
  filters: AuditFilters,
): Promise<{ entries: Entry[]; total: number }> {
  // Fixed at the start, so rows added while exporting do not shift the pages (addendum B3).
  const snapshot = { ...filters, to: filters.to ?? new Date().toISOString() };
  const entries: Entry[] = [];
  let total = 0;
  for (let page = 1; entries.length < MAX_EXPORT_ROWS; page++) {
    const result = await api.GET("/admin/audit", {
      params: { query: { ...snapshot, page, page_size: PAGE } },
    });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    total = result.data.total;
    entries.push(...result.data.items);
    if (result.data.items.length < PAGE || entries.length >= total) break;
  }
  return { entries: entries.slice(0, MAX_EXPORT_ROWS), total };
}
