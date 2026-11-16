/** Audit CSV export through `GET /admin/audit/export`, which records the export (CP-10, 8.2). */
import { api } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export interface AuditFilters {
  actor?: string;
  action?: string;
  entity_type?: string;
  from?: string;
  to?: string;
}

export interface ExportResult {
  blob: Blob;
  rows: number;
  truncated: boolean;
}

export async function exportAudit(
  filters: AuditFilters,
): Promise<ExportResult> {
  const result = await api.GET("/admin/audit/export", {
    params: { query: filters },
    parseAs: "blob",
  });
  if (!result.response.ok || result.data === undefined) throw failure(result);
  return {
    blob: result.data,
    rows: Number(result.response.headers.get("X-Export-Rows") ?? 0),
    truncated: result.response.headers.get("X-Export-Truncated") === "true",
  };
}
