/** The user tab (M9): preferences, sessions and the views a landing view can be. */
import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure, meQuery } from "@/lib/auth/session";

export type Preferences = Schemas["Preferences"];
export type SessionInfo = Schemas["SessionInfo"];

export const preferencesQuery = queryOptions({
  queryKey: ["me", "preferences"],
  queryFn: async (): Promise<Preferences> => {
    const result = await api.GET("/me/preferences");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

export const sessionsQuery = queryOptions({
  queryKey: ["me", "sessions"],
  queryFn: async (): Promise<SessionInfo[]> => {
    const result = await api.GET("/me/sessions");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

export const viewsQuery = queryOptions({
  queryKey: ["views"],
  queryFn: async () => {
    const result = await api.GET("/views");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

/** Save some preferences; the shell re-applies the appearance from the refreshed user. */
export function useSavePreferences() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (changes: Partial<Preferences>) => {
      // The generated type marks every field required (they have defaults); the API merges a
      // partial body, as the contract's PATCH means.
      const result = await api.PATCH("/me/preferences", {
        body: changes as Preferences,
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSuccess: (saved) => {
      client.setQueryData(preferencesQuery.queryKey, saved);
      return client.invalidateQueries({ queryKey: meQuery.queryKey });
    },
  });
}

export function useRevokeSession() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.DELETE("/me/sessions/{id}", {
        params: { path: { id } },
      });
      if (!result.response.ok) throw failure(result);
    },
    onSuccess: () =>
      client.invalidateQueries({ queryKey: sessionsQuery.queryKey }),
  });
}

export type MyGroup = Schemas["MyGroup"];

/** The signed-in user's groups and their interests (M11.4b, CP-27). */
export const myGroupsQuery = queryOptions({
  queryKey: ["me", "groups"],
  queryFn: async (): Promise<MyGroup[]> => {
    const result = await api.GET("/me/groups");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
  staleTime: 5 * 60_000,
});

type Interests = Schemas["Interests"];

function chosen(i: Interests | undefined): i is Interests {
  return Boolean(
    i &&
    ((i.jurisdictions ?? []).length > 0 ||
      (i.regions ?? []).length > 0 ||
      Object.values(i.terms ?? {}).some((keys) => keys.length > 0)),
  );
}

/**
 * The interests the map and items open with: the user's own, or, when they have set none,
 * those of their first group (by name) that has some. `group` names it for the chip.
 */
export function effectiveInterests(
  own: Interests | undefined,
  groups: readonly MyGroup[] | undefined,
): { interests: Interests | undefined; group?: string } {
  if (chosen(own)) return { interests: own };
  const shared = groups?.find((g) => chosen(g.interests));
  return shared
    ? { interests: shared.interests, group: shared.name }
    : { interests: own };
}
