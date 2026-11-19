/** Items (M5 `POST /search`, M4 `GET /items/{id}`). */
import { queryOptions } from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type Query = Schemas["Query"];
export type ItemSummary = Schemas["ItemSummary"];
export type SearchResult = Schemas["SearchResult"];

export const searchQuery = (query: Query) =>
  queryOptions({
    queryKey: ["search", query],
    queryFn: async (): Promise<SearchResult> => {
      const result = await api.POST("/search", { body: query });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    staleTime: 30_000,
  });

export type ItemDetail = Schemas["ItemDetail"];

export const itemQuery = (id: string) =>
  queryOptions({
    queryKey: ["items", id],
    queryFn: async (): Promise<ItemDetail> => {
      const result = await api.GET("/items/{id}", { params: { path: { id } } });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  });

export type ItemVersion = Schemas["ItemVersion"];

export const versionsQuery = (id: string) =>
  queryOptions({
    queryKey: ["items", id, "versions"],
    queryFn: async (): Promise<ItemVersion[]> => {
      const result = await api.GET("/items/{id}/versions", {
        params: { path: { id } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  });

export const diffQuery = (id: string, from: number, to: number) =>
  queryOptions({
    queryKey: ["items", id, "diff", from, to],
    queryFn: async () => {
      const result = await api.GET("/items/{id}/diff", {
        params: { path: { id }, query: { from, to } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  });
