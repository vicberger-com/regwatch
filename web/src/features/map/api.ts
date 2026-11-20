/** Map activity (M5 `GET /map/activity`): rows per jurisdiction for a period and filters. */
import { queryOptions } from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type MapActivity = Schemas["MapActivity"];
export const PERIODS = [7, 30, 90, 365] as const;

/** The map's view: by country or region, optionally narrowed to one facet term (acceptance 2). */
export interface MapView {
  by: "country" | "region";
  facet?: string;
  term?: string;
}

export const activityQuery = (
  periodDays: number,
  view: MapView = { by: "country" },
) =>
  queryOptions({
    queryKey: [
      "map",
      "activity",
      periodDays,
      view.by,
      view.facet ?? "",
      view.term ?? "",
    ],
    queryFn: async (): Promise<MapActivity> => {
      const filters =
        view.facet && view.term
          ? JSON.stringify({ terms: { [view.facet]: [view.term] } })
          : undefined;
      const result = await api.GET("/map/activity", {
        params: {
          query: {
            period_days: periodDays,
            view_by: view.by,
            ...(filters ? { filters } : {}),
          },
        },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    staleTime: 60_000,
  });
