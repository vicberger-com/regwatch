/** Report layouts and fields (M7.1 API) for the Reports pages and the builder (M7.4). */
import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, API_BASE_URL, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type ReportLayout = Schemas["ReportLayout"];
export type ReportLayoutWrite = Schemas["ReportLayoutWrite"];
export type ReportField = Schemas["ReportField"];
/** Puck data; the contract types it as a plain object and the server checks its shape. */
export type LayoutData = NonNullable<ReportLayoutWrite["layout"]>;
export const asLayout = (data: object): LayoutData =>
  data as unknown as LayoutData;

export const layoutsQuery = queryOptions({
  queryKey: ["reports", "layouts"],
  queryFn: async (): Promise<ReportLayout[]> => {
    const result = await api.GET("/reports/layouts");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

export function layoutQuery(id: string) {
  return queryOptions({
    queryKey: ["reports", "layouts", id],
    queryFn: async (): Promise<ReportLayout> => {
      const result = await api.GET("/reports/layouts/{id}", {
        params: { path: { id } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  });
}

export const fieldsQuery = queryOptions({
  queryKey: ["reports", "fields"],
  queryFn: async (): Promise<ReportField[]> => {
    const result = await api.GET("/reports/fields");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
  staleTime: 5 * 60_000,
});

export function useSaveLayout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (args: { id?: string; body: ReportLayoutWrite }) => {
      const result = args.id
        ? await api.PATCH("/reports/layouts/{id}", {
            params: { path: { id: args.id } },
            body: args.body,
          })
        : await api.POST("/reports/layouts", { body: args.body });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSuccess: (saved) => {
      client.setQueryData(layoutQuery(saved.id).queryKey, saved);
      return client.invalidateQueries({ queryKey: layoutsQuery.queryKey });
    },
  });
}

export function useDeleteLayout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.DELETE("/reports/layouts/{id}", {
        params: { path: { id } },
      });
      if (!result.response.ok) throw failure(result);
    },
    onSettled: () =>
      client.invalidateQueries({ queryKey: layoutsQuery.queryKey }),
  });
}

/**
 * The server-rendered preview (M7.2) as a URL for a sandboxed frame (CP-35; BL-140 g): loaded
 * by URL, the page keeps its own CSP; a srcdoc frame would inherit the app's, which in
 * production blocks the report's styles. Checked first, so a refusal is shown as text.
 */
export async function previewUrl(
  id: string,
  params: Record<string, unknown> = {},
): Promise<string> {
  const url = `${API_BASE_URL}/reports/layouts/${encodeURIComponent(id)}/preview?params=${encodeURIComponent(JSON.stringify(params))}`;
  const result = await api.GET("/reports/layouts/{id}/preview", {
    params: { path: { id }, query: { params: JSON.stringify(params) } },
    parseAs: "text",
  });
  if (!result.response.ok) throw failure(result);
  return `${url}&t=${String(Date.now())}`; // a fresh render each time
}

export const templatesQuery = queryOptions({
  queryKey: ["reports", "templates"],
  queryFn: async () => {
    const result = await api.GET("/reports/templates");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
  staleTime: 5 * 60_000,
});
