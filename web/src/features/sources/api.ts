/** Sources, capture jobs, runs and health (M3). */
import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type Source = Schemas["Source"];
export type SourceWrite = Schemas["SourceWrite"];
export type CaptureJobWrite = Schemas["CaptureJobWrite"];
export type CaptureRun = Schemas["CaptureRun"];
export type SourceHealth = Schemas["SourceHealth"];
/** The answer of `POST /sources/{id}/test`, which the contract defines inline (CP-13). */
export interface SourceTestResult {
  candidates?: Schemas["Candidate"][];
  robots_decision?: string;
  warnings?: string[];
}

export const PAGE_SIZE = 50;

/**
 * Why a run ended as it did, for the people who fix sources (RSS review: admins should see
 * `unsafe-feed`, `malformed-feed` and `too-large` clearly, so a source is fixed, not retried).
 */
export const REASONS: Record<string, string> = {
  "no-connector": "No connector runs this kind of source yet.",
  "bad-config":
    "The saved settings are no longer valid; edit and save the source.",
  "unsafe-feed":
    "The feed uses XML features that are refused for safety (a DOCTYPE or entity declarations). Ask the publisher for a plain feed.",
  "malformed-feed":
    "The answer is not a well-formed RSS or Atom feed. Check the feed address.",
  "too-large": "The answer is larger than the size limit.",
  "blocked-by-provider":
    "The provider's firewall refused the request. It is not retried or worked around; ask the provider to allow the address.",
  "malformed-answer":
    "The API's answer could not be read. Check the provider settings.",
  "not-implemented":
    "This kind of source, provider or setting is not built yet.",
  "not-html": "The page is not HTML.",
  "too-deep": "The page is nested too deeply to read safely.",
  "too-slow": "The page took too long to read safely.",
  "parse-failed": "The page could not be read.",
  "unreadable-pages":
    "Several linked pages could not be read within the safety limits, so the run stopped.",
  "needs-contact":
    "This provider refuses anonymous requests. Set the contact email in Settings (general.contact_email) first.",
  "http-status": "The site answered with an error status.",
  unavailable:
    "The provider does not have the document in the asked form or language.",
  robots: "robots.txt does not allow it.",
  "rate-limited": "The site was busy; the next run tries again.",
  "private-address": "The address does not resolve to public addresses only.",
  dns: "The host name could not be resolved.",
  timeout: "The site did not answer in time.",
  connect: "The site could not be reached.",
  tls: "The site's certificate could not be verified.",
  protocol: "The site's answer was not valid HTTP.",
  "fetch-failed": "None of the documents could be fetched.",
  "some-failed": "Some documents could not be fetched.",
  "run-deadline":
    "The run stopped at its time limit; lower the items or raise the rate.",
  "bad-schedule": "The schedule cannot be computed; edit and save it.",
  "queue-unavailable": "The run could not be queued; try again.",
  abandoned: "The run did not finish; the next run tries again.",
  "internal-error": "The run failed on our side, not the source's.",
  disabled: "The source or its job was disabled before the run.",
};

export function sourcesQuery(page: number) {
  return queryOptions({
    queryKey: ["sources", "list", page],
    queryFn: async () => {
      const result = await api.GET("/sources", {
        params: { query: { page, page_size: PAGE_SIZE } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    placeholderData: keepPreviousData,
  });
}

export function runsQuery(jobId: string) {
  return queryOptions({
    queryKey: ["sources", "runs", jobId],
    queryFn: async () => {
      const result = await api.GET("/capture-runs", {
        params: { query: { job_id: jobId, page: 1, page_size: 20 } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  });
}

export function healthQuery(sourceId: string) {
  return queryOptions({
    queryKey: ["sources", "health", sourceId],
    queryFn: async () => {
      const result = await api.GET("/sources/{id}/health", {
        params: { path: { id: sourceId } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  });
}

function useSourcesMutation<T, R>(call: (input: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useSaveSource() {
  return useSourcesMutation(
    async (input: { id?: string; body: SourceWrite }) => {
      const result = input.id
        ? await api.PATCH("/sources/{id}", {
            params: { path: { id: input.id } },
            body: input.body,
          })
        : await api.POST("/sources", { body: input.body });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  );
}

export function useDisableSource() {
  return useSourcesMutation(async (id: string) => {
    const result = await api.DELETE("/sources/{id}", {
      params: { path: { id } },
    });
    if (!result.response.ok) throw failure(result);
  });
}

/** The dry run (CP-13): the source's first candidates, fetched by a worker, nothing stored. */
export function useTestSource() {
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.POST("/sources/{id}/test", {
        params: { path: { id } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  });
}

export function useRunNow() {
  return useSourcesMutation(async (jobId: string) => {
    const result = await api.POST("/capture-jobs/{id}/run-now", {
      params: { path: { id: jobId } },
    });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  });
}
