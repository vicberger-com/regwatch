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
export type MatchRules = Schemas["MatchRules"];

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

/** The size the API accepts for one request body (BodySizeLimitMiddleware). */
export const MAX_IMPORT_BYTES = 2 * 1024 * 1024;

export function useImportTaxonomy() {
  return useTaxonomyMutation(async (document: string) => {
    const result = await api.POST("/taxonomy/import", {
      body: document,
      bodySerializer: (body) => body,
      headers: { "Content-Type": "application/yaml" },
    });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  });
}

/** The whole taxonomy as a YAML file the browser saves. */
export async function exportTaxonomy(): Promise<Blob> {
  const result = await api.GET("/taxonomy/export", { parseAs: "blob" });
  if (!result.response.ok || result.data === undefined) throw failure(result);
  return result.data;
}

export function useUpdateTerm() {
  return useTaxonomyMutation(
    async (input: { id: string; body: Schemas["TermWrite"] }) => {
      const result = await api.PATCH("/taxonomy/terms/{id}", {
        params: { path: { id: input.id } },
        body: input.body,
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  );
}

/** Runs a term's saved rules against sample text; changes nothing, so no cache refresh. */
export function useTestRules() {
  return useMutation({
    mutationFn: async (input: {
      id: string;
      text: string;
      language?: string;
    }) => {
      const { id, ...body } = input;
      const result = await api.POST("/taxonomy/terms/{id}/test-rules", {
        params: { path: { id } },
        body,
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  });
}

/** Lines of a text area as a list: trimmed, blank lines dropped. */
export function lines(text: string): string[] {
  return text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function useMergeTerm() {
  return useTaxonomyMutation(async (input: { id: string; into: string }) => {
    const result = await api.POST("/taxonomy/terms/{id}/merge", {
      params: { path: { id: input.id } },
      body: { into_term_id: input.into },
    });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  });
}

export function useDeleteTerm() {
  return useTaxonomyMutation(async (id: string) => {
    const result = await api.DELETE("/taxonomy/terms/{id}", {
      params: { path: { id } },
    });
    if (!result.response.ok) throw failure(result);
  });
}
