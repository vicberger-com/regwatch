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
function failure(result: { error?: unknown; response: Response }): ApiProblem {
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
    onSuccess: (me) => client.setQueryData(meQuery.queryKey, me),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.POST("/auth/logout");
    },
    onSettled: () => {
      client.setQueryData(meQuery.queryKey, null);
      client.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
  });
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
      return "Too many attempts. Wait a minute and try again.";
    default:
      return problem.detail ?? "Sign-in failed. Try again.";
  }
}

export async function currentUser(client: QueryClient): Promise<Me | null> {
  return client.query(meQuery); // served from the cache while fresh (staleTime)
}
