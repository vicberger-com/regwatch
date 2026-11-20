/** Report layouts and fields (M7.1 API) for the Reports pages and the builder (M7.4). */
import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
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

/** The server-rendered preview (M7.2): HTML shown in a sandboxed frame, never inline. */
export async function previewHtml(id: string): Promise<string> {
  const result = await api.POST("/reports/layouts/{id}/preview", {
    params: { path: { id } },
    parseAs: "text",
  });
  if (!result.response.ok || typeof result.data !== "string")
    throw failure(result);
  return result.data;
}
