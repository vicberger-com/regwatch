/** Map activity (M5 `GET /map/activity`): rows per jurisdiction for a period and filters. */
import { queryOptions } from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type MapActivity = Schemas["MapActivity"];
export const PERIODS = [7, 30, 90, 365] as const;

export const activityQuery = (periodDays: number, viewBy = "country") =>
  queryOptions({
    queryKey: ["map", "activity", periodDays, viewBy],
    queryFn: async (): Promise<MapActivity> => {
      const result = await api.GET("/map/activity", {
        params: { query: { period_days: periodDays, view_by: viewBy } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    staleTime: 60_000,
  });
