/** Taxonomy data (M2): facets with their term trees, and the create calls. */
import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

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

function useTaxonomyMutation<T, R>(call: (input: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: () => client.invalidateQueries({ queryKey: ["taxonomy"] }),
  });
}

export function useCreateFacet() {
  return useTaxonomyMutation(async (body: Schemas["FacetWrite"]) => {
    const result = await api.POST("/taxonomy/facets", { body });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  });
}

export function useCreateTerm() {
  return useTaxonomyMutation(
    async (input: { facet: string; body: Schemas["TermWrite"] }) => {
      const result = await api.POST("/taxonomy/facets/{key}/terms", {
        params: { path: { key: input.facet } },
        body: input.body,
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  );
}

/** Every term of a tree, depth first, with its depth (for the parent picker); iterative, so a
 * deep hierarchy cannot overflow the stack (web review finding 9). */
export function flatten(terms: Term[]): { term: Term; depth: number }[] {
  const out: { term: Term; depth: number }[] = [];
  const stack = [...terms].reverse().map((term) => ({ term, depth: 0 }));
  for (let next = stack.pop(); next; next = stack.pop()) {
    out.push(next);
    const children = next.term.children ?? [];
    for (let i = children.length - 1; i >= 0; i--) {
      const child = children[i];
      if (child) stack.push({ term: child, depth: next.depth + 1 });
    }
  }
  return out;
}
