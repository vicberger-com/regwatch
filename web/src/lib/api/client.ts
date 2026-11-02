/**
 * Typed API client: `schema.d.ts` is generated from openapi/regwatch.v1.yaml by
 * `make openapi` (openapi-typescript); requests go through openapi-fetch.
 *
 * The session cookie `rw_session` is same-origin, so the browser sends it and the
 * Origin header (CSRF check) on its own. Errors are RFC 9457 problem details.
 */
import createClient, { type ClientOptions } from "openapi-fetch";

import type { components, paths } from "./schema";

export type { components, paths };
export type Schemas = components["schemas"];
export type Problem = Schemas["Problem"];

export const API_BASE_URL = "/api/v1";

export function createApiClient(options: ClientOptions = {}) {
  return createClient<paths>({
    baseUrl: API_BASE_URL,
    credentials: "same-origin",
    headers: { Accept: "application/json, application/problem+json" },
    ...options,
  });
}

export const api = createApiClient();

export function isProblem(value: unknown): value is Problem {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.type === "string" &&
    typeof v.title === "string" &&
    typeof v.status === "number"
  );
}
