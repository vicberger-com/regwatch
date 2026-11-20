/**
 * Feed requests (M11.3, CP-26): users ask for a feed that is not in the catalogue; editors
 * create the source in the source editor, where every check applies, then approve the
 * request with it, or decline it. A requested URL is shown as text, never as a link: nobody
 * has checked it yet.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { failure, problemText } from "@/lib/auth/session";

import { sourcesQuery } from "./api";
import { sourceState } from "./SourcesPage";

export type FeedRequest = Schemas["FeedRequest"];
const CATALOGUE_KINDS = new Set(["rss", "api_feed", "web_page"]); // as the API allows

/** The host alone (stored in punycode by the API), so a look-alike name is plain to see. */
function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";
const STATUS: Record<FeedRequest["status"], string> = {
  pending: "Waiting for an editor",
  approved: "Added to the catalogue",
  declined: "Declined",
  withdrawn: "Withdrawn",
};

export function requestsQuery(status?: FeedRequest["status"]) {
  return {
    queryKey: ["feed-requests", status ?? "all"],
    queryFn: async (): Promise<FeedRequest[]> => {
      const result = await api.GET("/feed-requests", {
        params: { query: status ? { status } : {} },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
  };
}

function useRefresh() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["feed-requests"] }),
      client.invalidateQueries({ queryKey: ["catalogue"] }),
      client.invalidateQueries({ queryKey: ["sources"] }),
    ]);
}

/** The User tab's request form and the user's own requests. */
export function RequestFeed() {
  const id = useId();
  const refresh = useRefresh();
  const [url, setUrl] = useState("");
  const [reason, setReason] = useState("");
  const mine = useQuery(requestsQuery());
  const ask = useMutation({
    mutationFn: async () => {
      const result = await api.POST("/feed-requests", {
        body: { url: url.trim(), reason: reason.trim() },
      });
      if (!result.response.ok) throw failure(result);
    },
    onSuccess: () => {
      setUrl("");
      setReason("");
    },
    onSettled: refresh,
  });
  const withdraw = useMutation({
    mutationFn: async (requestId: string) => {
      const result = await api.DELETE("/feed-requests/{id}", {
        params: { path: { id: requestId } },
      });
      if (!result.response.ok) throw failure(result);
    },
    onSettled: refresh,
  });
  return (
    <div className="grid gap-3">
      <form
        aria-label="Ask for a feed"
        className="grid gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          ask.mutate();
        }}
      >
        <h3 className="text-sm font-semibold">Ask for a feed</h3>
        <label htmlFor={`${id}-url`} className="text-sm">
          Feed or page address (https)
        </label>
        <input
          id={`${id}-url`}
          type="url"
          required
          maxLength={2048}
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
          }}
          className="rounded border border-border px-2 py-1"
        />
        <label htmlFor={`${id}-reason`} className="text-sm">
          Why it matters
        </label>
        <textarea
          id={`${id}-reason`}
          required
          maxLength={1000}
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
          }}
          className="rounded border border-border px-2 py-1"
        />
        <div>
          <button type="submit" className={button} disabled={ask.isPending}>
            Send the request
          </button>
        </div>
        {ask.isError && (
          <p role="alert" className="text-sm">
            {problemText(ask.error, "The request could not be sent.")}
          </p>
        )}
        {ask.isSuccess && (
          <p role="status" className="text-sm">
            Sent. An editor will check the feed.
          </p>
        )}
      </form>
      {mine.data && mine.data.length > 0 && (
        <ul aria-label="Your requests" className="grid gap-2 text-sm">
          {mine.data.map((r) => (
            <li key={r.id} className="rounded border border-border p-2">
              <span className="block break-all font-mono">{r.url}</span>
              <span className="block">{STATUS[r.status]}</span>
              {r.decision_note && (
                <span className="block text-text-muted">
                  Editor's note: {r.decision_note}
                </span>
              )}
              {r.status === "pending" && (
                <button
                  type="button"
                  className={`${button} mt-1`}
                  disabled={withdraw.isPending}
                  aria-label={`Withdraw the request for ${r.url}`}
                  onClick={() => {
                    withdraw.mutate(r.id);
                  }}
                >
                  Withdraw
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {withdraw.isError && (
        <p role="alert" className="text-sm">
          {problemText(withdraw.error, "The request could not be withdrawn.")}
        </p>
      )}
    </div>
  );
}

function Decide({ request }: { request: FeedRequest }) {
  const id = useId();
  const refresh = useRefresh();
  const sources = useQuery(sourcesQuery(1));
  const [sourceId, setSourceId] = useState("");
  const [summary, setSummary] = useState("");
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: async (decision: "approved" | "declined") => {
      const result = await api.POST("/feed-requests/{id}/decision", {
        params: { path: { id: request.id } },
        body:
          decision === "approved"
            ? {
                decision,
                source_id: sourceId,
                summary: summary.trim() || null,
                note: note.trim() || null,
              }
            : { decision, note: note.trim() || null },
      });
      if (!result.response.ok) throw failure(result);
    },
    onSettled: refresh,
  });
  const chosen = sources.data?.items.find((s) => s.id === sourceId);
  return (
    <li className="grid gap-2 rounded border border-border p-3 text-sm">
      <span className="block">
        Host: <span className="font-mono">{hostOf(request.url)}</span>
      </span>
      <span className="block break-all font-mono">{request.url}</span>
      <span className="block">
        From {request.requested_by ?? "a user"}: {request.reason}
      </span>
      <label htmlFor={`${id}-source`}>
        Source created for it (add it under Sources first)
      </label>
      <select
        id={`${id}-source`}
        value={sourceId}
        onChange={(e) => {
          setSourceId(e.target.value);
        }}
        className="rounded border border-border px-2 py-1"
      >
        <option value="">Choose a source</option>
        {sources.data?.items
          .filter((s) => CATALOGUE_KINDS.has(s.kind))
          .map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
      </select>
      {chosen && (
        <p className="text-text-muted">
          {chosen.kind} · robots.txt: {chosen.robots_policy ?? "respect"} ·{" "}
          {sourceState(chosen)}
        </p>
      )}
      {chosen && !chosen.catalogue_key && (
        <>
          <label htmlFor={`${id}-summary`}>One line for the catalogue</label>
          <input
            id={`${id}-summary`}
            maxLength={300}
            value={summary}
            onChange={(e) => {
              setSummary(e.target.value);
            }}
            className="rounded border border-border px-2 py-1"
          />
        </>
      )}
      <label htmlFor={`${id}-note`}>Note to the requester</label>
      <input
        id={`${id}-note`}
        maxLength={1000}
        value={note}
        onChange={(e) => {
          setNote(e.target.value);
        }}
        className="rounded border border-border px-2 py-1"
      />
      <div className="flex gap-2">
        <button
          type="button"
          className={button}
          disabled={!sourceId || decide.isPending}
          aria-label={`Approve the request for ${request.url}`}
          onClick={() => {
            decide.mutate("approved");
          }}
        >
          Approve
        </button>
        <button
          type="button"
          className={button}
          disabled={decide.isPending}
          aria-label={`Decline the request for ${request.url}`}
          onClick={() => {
            decide.mutate("declined");
          }}
        >
          Decline
        </button>
      </div>
      {decide.isError && (
        <p role="alert">
          {problemText(decide.error, "The decision could not be saved.")}
        </p>
      )}
    </li>
  );
}

/** Editors' queue of waiting requests, on the Sources page. */
export function RequestQueue() {
  const waiting = useQuery(requestsQuery("pending"));
  if (waiting.isPending) return null;
  if (waiting.isError)
    return (
      <p role="alert" className="text-sm">
        {problemText(waiting.error, "The feed requests could not be loaded.")}
      </p>
    );
  return (
    <section aria-labelledby="requests-heading" className="grid gap-2">
      <h2 id="requests-heading" className="text-lg font-semibold">
        Feed requests ({waiting.data.length} waiting)
      </h2>
      {waiting.data.length === 0 ? (
        <p className="text-sm text-text-muted">No requests are waiting.</p>
      ) : (
        <ul className="grid gap-2">
          {waiting.data.map((r) => (
            <Decide key={r.id} request={r} />
          ))}
        </ul>
      )}
    </section>
  );
}
