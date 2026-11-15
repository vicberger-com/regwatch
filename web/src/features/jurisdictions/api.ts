/** Jurisdictions (M2): the list, UN M49 regions, and the create and update calls. */
import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type Jurisdiction = Schemas["Jurisdiction"];
export type JurisdictionWrite = Schemas["JurisdictionWrite"];
export const KINDS = ["country", "subdivision", "supranational"] as const;

export const jurisdictionsQuery = queryOptions({
  queryKey: ["jurisdictions", "all"],
  queryFn: async (): Promise<Jurisdiction[]> => {
    const result = await api.GET("/jurisdictions");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

export const regionsQuery = queryOptions({
  queryKey: ["jurisdictions", "regions"],
  queryFn: async () => {
    const result = await api.GET("/jurisdictions/regions");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
  staleTime: Infinity,
});

export function useSaveJurisdiction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: { code?: string; body: JurisdictionWrite }) => {
      const result = input.code
        ? await api.PATCH("/jurisdictions/{code}", {
            params: { path: { code: input.code } },
            body: input.body,
          })
        : await api.POST("/jurisdictions", { body: input.body });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSuccess: () =>
      client.invalidateQueries({ queryKey: jurisdictionsQuery.queryKey }),
  });
}
