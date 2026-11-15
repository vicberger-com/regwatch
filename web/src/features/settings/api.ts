/** Runtime settings and feature flags (#32). */
import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type FeatureFlag = Schemas["FeatureFlag"];

export const flagsQuery = queryOptions({
  queryKey: ["admin", "flags"],
  queryFn: async (): Promise<FeatureFlag[]> => {
    const result = await api.GET("/admin/feature-flags");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

export function useSetFlag() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: { key: string; enabled: boolean }) => {
      const result = await api.PATCH("/admin/feature-flags/{key}", {
        params: { path: { key: input.key } },
        body: { enabled: input.enabled },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSettled: () =>
      client.invalidateQueries({ queryKey: flagsQuery.queryKey }),
  });
}
