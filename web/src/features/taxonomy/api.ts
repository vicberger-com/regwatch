/** Taxonomy data (M2): facets with their term trees. */
import { queryOptions } from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type Facet = Schemas["Facet"];
export type Term = Schemas["Term"];

export const facetsQuery = queryOptions({
  queryKey: ["taxonomy", "facets"],
  queryFn: async (): Promise<Facet[]> => {
    const result = await api.GET("/taxonomy/facets");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

/** Every term of a tree, depth first, with its depth (for the parent picker). */
export function flatten(
  terms: Term[],
  depth = 0,
): { term: Term; depth: number }[] {
  return terms.flatMap((term) => [
    { term, depth },
    ...flatten(term.children ?? [], depth + 1),
  ]);
}
