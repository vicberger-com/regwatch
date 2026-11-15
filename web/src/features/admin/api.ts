/** Admin data for the users screen (#32): queries and mutations over the generated client. */
import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type User = Schemas["User"];
export type Role = Schemas["Role"];

const PAGE_SIZE = 200; // the API's maximum
const MAX_PAGES = 50;
/** The most users the screen loads; beyond it the screen says the list is incomplete. */
export const MAX_USERS = PAGE_SIZE * MAX_PAGES;

export const usersQuery = queryOptions({
  queryKey: ["admin", "users"],
  // Every page, so no account is out of reach (web review finding 8).
  queryFn: async (): Promise<User[]> => {
    const users: User[] = [];
    for (let page = 1; page <= MAX_PAGES; page++) {
      const result = await api.GET("/admin/users", {
        params: { query: { page, page_size: PAGE_SIZE } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      users.push(...result.data.items);
      if (users.length >= result.data.total || result.data.items.length === 0)
        break;
    }
    return users;
  },
});

export const rolesQuery = queryOptions({
  queryKey: ["admin", "roles"],
  queryFn: async (): Promise<Role[]> => {
    const result = await api.GET("/admin/roles");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

function useAdminMutation<T, R>(call: (input: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    gcTime: 0, // results can hold a temporary password (web review finding 2)
    onSuccess: () =>
      client.invalidateQueries({ queryKey: usersQuery.queryKey }),
  });
}

export function useCreateUser() {
  return useAdminMutation(async (body: Schemas["UserCreate"]) => {
    const result = await api.POST("/admin/users", { body });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  });
}

export function useUpdateUser() {
  return useAdminMutation(
    async (input: { id: string; body: Schemas["UserUpdate"] }) => {
      const result = await api.PATCH("/admin/users/{id}", {
        params: { path: { id: input.id } },
        body: input.body,
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  );
}

export function useResetPassword() {
  return useAdminMutation(async (id: string) => {
    const result = await api.POST("/admin/users/{id}/reset-password", {
      params: { path: { id } },
    });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data.temporary_password ?? "";
  });
}
