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
