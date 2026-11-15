/** Runtime settings and feature flags (#32). */
import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type FeatureFlag = Schemas["FeatureFlag"];

export const flagsQuery = queryOptions({
  queryKey: ["admin", "flags"],
  queryFn: async (): Promise<FeatureFlag[]> => {
    const result = await api.GET("/admin/feature-flags");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

export function useSetFlag() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: { key: string; enabled: boolean }) => {
      const result = await api.PATCH("/admin/feature-flags/{key}", {
        params: { path: { key: input.key } },
        body: { enabled: input.enabled },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSettled: () =>
      client.invalidateQueries({ queryKey: flagsQuery.queryKey }),
  });
}

export type Setting = Schemas["Setting"];

export const settingsQuery = queryOptions({
  queryKey: ["admin", "settings"],
  queryFn: async (): Promise<Setting[]> => {
    const result = await api.GET("/admin/settings");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

export function useSaveSetting() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: { key: string; value: unknown }) => {
      const result = await api.PUT("/admin/settings/{key}", {
        params: { path: { key: input.key } },
        body: { value: input.value },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSuccess: () =>
      client.invalidateQueries({ queryKey: settingsQuery.queryKey }),
  });
}

/** The text a setting is edited as: list items one per line, everything else as typed. */
export function toText(setting: Setting): string {
  const v = setting.value;
  if (Array.isArray(v)) return v.map(String).join("\n");
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean")
    return String(v);
  return "";
}

/** The value to send for edited text, or an error message; the API checks again. */
export function parseValue(
  setting: Setting,
  text: string,
): { value: unknown } | { error: string } {
  switch (setting.type) {
    case "integer":
      return /^-?\d+$/.test(text.trim()) && Number.isSafeInteger(Number(text))
        ? { value: Number(text) }
        : { error: "Enter a whole number." };
    case "number": {
      const n = Number(text);
      return text.trim() !== "" && Number.isFinite(n) && n >= 0
        ? { value: n }
        : { error: "Enter a number of zero or more." };
    }
    case "boolean":
      return { value: text === "true" };
    case "enum":
      return (setting.values ?? []).includes(text)
        ? { value: text }
        : { error: "Choose one of the listed values." };
    case "list":
      return {
        value: text
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      };
    default:
      return { value: text };
  }
}

/** Settings grouped by the prefix of their key (`auth.lockout_minutes` is in `auth`). */
export function groupByPrefix(settings: Setting[]): [string, Setting[]][] {
  const groups = new Map<string, Setting[]>();
  for (const s of [...settings].sort((a, b) => a.key.localeCompare(b.key))) {
    const prefix = s.key.split(".")[0] ?? s.key;
    groups.set(prefix, [...(groups.get(prefix) ?? []), s]);
  }
  return [...groups];
}
