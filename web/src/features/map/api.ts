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

export type Filters = NonNullable<Schemas["Query"]["filters"]>;

export const MAX_JURISDICTIONS = 300; // the search filter's cap (CP-24)

/**
 * The user's interests as query filters (M11.1). Places combine as any of: the chosen
 * jurisdictions and every member of the chosen regions form one jurisdiction list. Topics
 * combine as any of within a facet, and every facet chosen must match. Past the cap, the
 * regions are sent alone (chosen jurisdictions outside them are left out). Without the
 * options (not loaded yet, or refused), the chosen jurisdictions are sent alone, or the
 * regions when none is chosen: never both, whose intersection may be empty.
 */

export function interestFilters(
  i: Schemas["Interests"] | undefined,
  options?: Schemas["InterestOptions"],
): Filters {
  const out: Filters = {};
  const chosen = i?.jurisdictions ?? [];
  const chosenRegions = i?.regions ?? [];
  if (options && chosenRegions.length > 0) {
    // Places are any-of: the chosen jurisdictions plus the members of the chosen regions.
    const members = options.regions
      .filter((r) => chosenRegions.includes(r.key))
      .flatMap((r) => r.members);
    const places = [...new Set([...chosen, ...members])].sort();
    if (places.length > MAX_JURISDICTIONS)
      out.regions = chosenRegions; // too many: regions alone
    else if (places.length > 0) out.jurisdictions = places;
  } else if (chosen.length > 0) {
    // Without the region members (options not loaded), the jurisdictions alone: a part of
    // the any-of, never the empty intersection of jurisdictions and regions.
    out.jurisdictions = chosen;
  } else if (chosenRegions.length > 0) {
    out.regions = chosenRegions;
  }
  const terms = Object.fromEntries(
    Object.entries(i?.terms ?? {}).filter(([, keys]) => keys.length > 0),
  );
  if (Object.keys(terms).length > 0) out.terms = terms;
  return out;
}

export const activityQuery = (
  periodDays: number,
  view: MapView = { by: "country" },
  extra: Filters = {},
) =>
  queryOptions({
    queryKey: [
      "map",
      "activity",
      periodDays,
      view.by,
      view.facet ?? "",
      view.term ?? "",
      extra,
    ],
    queryFn: async (): Promise<MapActivity> => {
      // The view's facet term narrows that facet; the interests filter the rest (M11.1).
      const merged: Filters = {
        ...extra,
        ...(view.facet && view.term
          ? { terms: { ...(extra.terms ?? {}), [view.facet]: [view.term] } }
          : {}),
      };
      const filters =
        Object.keys(merged).length > 0 ? JSON.stringify(merged) : undefined;
      const result = await api.GET("/map/activity", {
        // Passive: the map's own polling never keeps an idle session alive on the server.
        headers: { "X-Regwatch-Passive": "1" },
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
    // Live changes (G3): asked again every minute while the page is visible.
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
