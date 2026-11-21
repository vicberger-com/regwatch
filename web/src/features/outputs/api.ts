/** Output jobs (M8 API) for the Outputs page (M8.6): history, schedules, retry and cancel. */
import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, API_BASE_URL, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type OutputJob = Schemas["OutputJob"];
export type Scope = "mine" | "all";
export const PAGE_SIZE = 25;

export function outputsQuery(scope: Scope, scheduled: boolean, page: number) {
  return queryOptions({
    queryKey: ["outputs", scope, scheduled, page],
    queryFn: async () => {
      const result = await api.GET("/outputs", {
        params: { query: { scope, scheduled, page, page_size: PAGE_SIZE } },
        // Passive: this list polls while jobs run, and must never keep an idle session alive
        // on the server (M8.6 review), as the map's polling.
        headers: { "X-Regwatch-Passive": "1" },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    placeholderData: keepPreviousData,
    // Queued and rendering jobs change on their own: look again while any is in flight.
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (j) => !j.scheduled_cron && ["queued", "rendering"].includes(j.status),
      )
        ? 5_000
        : false,
  });
}

/** The download: the API answers with a redirect to a link signed for 10 minutes (CP-32). */
export const artifactHref = (id: string) =>
  `${API_BASE_URL}/outputs/${encodeURIComponent(id)}/artifact`;

export function useRetry() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.POST("/outputs/{id}/retry", {
        params: { path: { id } },
      });
      if (!result.response.ok) throw failure(result);
      return result.data;
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["outputs"] }),
  });
}

export function useCancel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.DELETE("/outputs/{id}", {
        params: { path: { id } },
      });
      if (!result.response.ok) throw failure(result);
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["outputs"] }),
  });
}

export type OutputRequest = Schemas["OutputRequest"];

export function useCreateOutput() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: OutputRequest) => {
      const result = await api.POST("/outputs", { body });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["outputs"] }),
  });
}

export { templatesQuery } from "@/features/reports/api";

/** CP-33: the printers New output offers; null while server printing is off (404). */
export const printerChoicesQuery = queryOptions({
  queryKey: ["printers"],
  queryFn: async () => {
    const result = await api.GET("/printers");
    if (result.response.status === 404) return null;
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});
