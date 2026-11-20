/**
 * The signed-in user (#31): `GET /auth/me` through TanStack Query, plus sign-in, sign-out and
 * password change. A 401 from `/auth/me` means "not signed in" and is cached as `null`; the
 * API's session gate is the authority, this only decides what the UI shows.
 */
import {
  queryOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { api, isProblem, type Problem, type Schemas } from "@/lib/api/client";

export type Me = Schemas["Me"];

export class ApiProblem extends Error {
  constructor(readonly problem: Problem) {
    super(problem.detail ?? problem.title);
  }
}

function toProblem(error: unknown, status: number): Problem {
  if (isProblem(error)) return error;
  return { type: "about:blank", title: "Request failed", status };
}

/** The error body of a failed call, whatever the contract says the route can return. */
export function failure(result: {
  error?: unknown;
  response: Response;
}): ApiProblem {
  return new ApiProblem(toProblem(result.error, result.response.status));
}

export const meQuery = queryOptions({
  queryKey: ["me"],
  queryFn: async (): Promise<Me | null> => {
    const result = await api.GET("/auth/me");
    if (result.response.status === 401) return null;
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
  staleTime: 30_000,
  retry: false,
});

export function hasPermission(me: Me | null | undefined, key: string): boolean {
  return me?.permissions?.includes(key) ?? false;
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: { email: string; password: string }) => {
      const result = await api.POST("/auth/login", {
        body: { ...input, remember_me: false },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    // A new sign-in starts from an empty cache, so nothing of a previous user is shown
    // (web review finding 3), and the typed password is not kept (finding 2).
    onSuccess: (me) => {
      forgetEverything(client);
      client.setQueryData(meQuery.queryKey, me);
    },
    gcTime: 0,
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const result = await api.POST("/auth/logout");
      // 401: the session had already ended, which is what signing out wants.
      if (!result.response.ok && result.response.status !== 401)
        throw failure(result);
    },
    // Only a confirmed sign-out clears the screen (web review finding 1); on failure the user
    // stays signed in and is told so, rather than seeing a sign-in card over a live session.
    onSuccess: () => {
      forgetEverything(client);
      client.setQueryData(meQuery.queryKey, null);
    },
  });
}

/** Drop every cached query and mutation, passwords in mutation variables included. */
export function forgetEverything(client: QueryClient): void {
  client.getMutationCache().clear();
  client.clear();
  try {
    // The last user's appearance hints at personal needs on a shared device (M9 review).
    window.localStorage.removeItem("regwatch.appearance");
  } catch {
    // storage refused: nothing was kept
  }
}

export function useChangePassword() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      current_password: string;
      new_password: string;
    }) => {
      const result = await api.POST("/auth/password", { body: input });
      if (!result.response.ok) throw failure(result);
    },
    gcTime: 0, // the current and new passwords are not kept once the form is gone
    onSuccess: () => client.invalidateQueries({ queryKey: meQuery.queryKey }),
  });
}

/** Messages for the sign-in answers the API documents (401, 423, 429). */
export function loginErrorMessage(problem: Problem): string {
  switch (problem.status) {
    case 401:
      return "The email or password is incorrect.";
    case 423:
      return "This account is locked. Try again later or ask an administrator.";
    case 429:
      return "Too many attempts. Wait and try again.";
    default:
      return problem.detail ?? "Sign-in failed. Try again.";
  }
}

export async function currentUser(client: QueryClient): Promise<Me | null> {
  return client.query(meQuery); // served from the cache while fresh (staleTime)
}

/** The text to show for a failed call: the problem's detail, else a fallback. */
export function problemText(error: unknown, fallback: string): string {
  if (!(error instanceof ApiProblem)) return error ? fallback : "";
  const fields = (error.problem.errors ?? [])
    .map((e) =>
      e.field ? `${e.field}: ${e.message ?? ""}` : (e.message ?? ""),
    )
    .filter(Boolean);
  return fields.length > 0
    ? fields.join("; ")
    : (error.problem.detail ?? fallback);
}
