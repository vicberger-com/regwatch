/** Jurisdictions (M2): the list and the UN M49 regions. */
import { queryOptions } from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type Jurisdiction = Schemas["Jurisdiction"];
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
