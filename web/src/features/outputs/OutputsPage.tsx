/**
 * `/outputs` (screens.md; M8.6): the output history and the scheduled outputs, mine or (with
 * `outputs.read_all`) everyone's; download, retry and cancel. Only the requester may retry or
 * cancel (the API checks it again).
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Tabs } from "@/features/items/Tabs";
import { problemText } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/time/format";

import {
  artifactHref,
  outputsQuery,
  PAGE_SIZE,
  useCancel,
  useRetry,
  type OutputJob,
  type Scope,
} from "./api";
import { NewOutput } from "./NewOutput";

const button = "rounded border border-border px-2 py-1 disabled:opacity-50";
const KIND: Record<string, string> = {
  pdf: "PDF",
  email: "Email",
  csv: "CSV",
  print: "Print",
};
const STATUS: Record<string, string> = {
  queued: "Queued",
  rendering: "Working",
  sent: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

function why(job: OutputJob): string | null {
  if (job.error_class === "source-deleted")
    return "Its report or saved view was deleted.";
  return job.error_message ?? job.error_class ?? null;
}

export function OutputsPage(props: {
  userId: string;
  canReadAll: boolean;
  can: (permission: string) => boolean;
  initial?: string;
}) {
  const [tab, setTab] = useState("history");
  const [scope, setScope] = useState<Scope>("mine");
  const [creating, setCreating] = useState(Boolean(props.initial));
  return (
    <section aria-labelledby="outputs-heading" className="flex flex-col gap-4">
      <h1 id="outputs-heading" className="text-2xl font-semibold">
        Outputs
      </h1>
      <div>
        <button
          type="button"
          className={button}
          aria-expanded={creating}
          onClick={() => {
            setCreating(!creating);
          }}
        >
          New output
        </button>
      </div>
      {creating && (
        <NewOutput
          can={props.can}
          {...(props.initial ? { initial: props.initial } : {})}
        />
      )}
      {props.canReadAll && (
        <fieldset className="flex gap-4 text-sm">
          <legend className="sr-only">Whose outputs</legend>
          {(["mine", "all"] as const).map((s) => (
            <label key={s} className="flex items-center gap-1">
              <input
                type="radio"
                name="outputs-scope"
                checked={scope === s}
                onChange={() => {
                  setScope(s);
                }}
              />
              {s === "mine" ? "Mine" : "Everyone's"}
            </label>
          ))}
        </fieldset>
      )}
      <Tabs
        label="Outputs"
        active={tab}
        onChange={setTab}
        tabs={[
          {
            id: "history",
            label: "History",
            panel: () => (
              <JobTable scope={scope} scheduled={false} userId={props.userId} />
            ),
          },
          {
            id: "schedules",
            label: "Schedules",
            panel: () => (
              <JobTable scope={scope} scheduled userId={props.userId} />
            ),
          },
        ]}
      />
    </section>
  );
}

function JobTable(props: { scope: Scope; scheduled: boolean; userId: string }) {
  const [page, setPage] = useState(1);
  const jobs = useQuery(outputsQuery(props.scope, props.scheduled, page));
  const retry = useRetry();
  const cancel = useCancel();
  if (jobs.isPending) return <p>Loading outputs…</p>;
  if (jobs.isError)
    return (
      <p role="alert" className="text-critical">
        {problemText(jobs.error, "The outputs could not be loaded.")}
      </p>
    );
  const { items, total } = jobs.data;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const failed = retry.error ?? cancel.error;
  return (
    <div className="flex flex-col gap-2">
      {failed && (
        <p role="alert" className="text-critical">
          {problemText(failed, "The change could not be made.")}
        </p>
      )}
      {items.length === 0 ? (
        <p className="text-sm text-text-muted">
          {props.scheduled ? "No scheduled outputs." : "No outputs yet."}
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th scope="col" className="text-left">
                Kind
              </th>
              <th scope="col" className="text-left">
                Source
              </th>
              <th scope="col" className="text-left">
                Destination
              </th>
              {props.scheduled ? (
                <>
                  <th scope="col" className="text-left">
                    Schedule
                  </th>
                  <th scope="col" className="text-left">
                    Next run
                  </th>
                </>
              ) : (
                <th scope="col" className="text-left">
                  Created
                </th>
              )}
              <th scope="col" className="text-left">
                Status
              </th>
              <th scope="col" className="text-left">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((job) => {
              const mine = job.requested_by === props.userId;
              const name = `${KIND[job.kind] ?? job.kind} of ${job.source_summary ?? "a report"}, ${formatDateTime(job.created_at)}`;
              const paused = props.scheduled && job.status === "failed";
              const reason = why(job);
              return (
                <tr key={job.id}>
                  <td>{KIND[job.kind] ?? job.kind}</td>
                  <td>{job.source_summary}</td>
                  <td>{job.destination_summary}</td>
                  {props.scheduled ? (
                    <>
                      <td>
                        <code>{job.scheduled_cron}</code>
                      </td>
                      <td>
                        {job.next_run_at
                          ? formatDateTime(job.next_run_at)
                          : "—"}
                      </td>
                    </>
                  ) : (
                    <td>{formatDateTime(job.created_at)}</td>
                  )}
                  <td>
                    {paused
                      ? "Paused"
                      : props.scheduled && job.status === "queued"
                        ? "Active"
                        : (STATUS[job.status] ?? job.status)}
                    {reason && job.status !== "sent" && (
                      <span className="block text-text-muted">{reason}</span>
                    )}
                  </td>
                  <td className="flex flex-wrap gap-2">
                    {job.artifact_available && (
                      <a
                        className="text-accent underline"
                        href={artifactHref(job.id)}
                        aria-label={`Download ${name}`}
                      >
                        Download
                      </a>
                    )}
                    {mine && job.status === "failed" && (
                      <button
                        type="button"
                        className={button}
                        aria-label={`${paused ? "Resume" : "Retry"} ${name}`}
                        disabled={retry.isPending}
                        onClick={() => {
                          retry.mutate(job.id);
                        }}
                      >
                        {paused ? "Resume" : "Retry"}
                      </button>
                    )}
                    {mine &&
                      (job.status === "queued" ||
                        (props.scheduled && job.status === "failed")) && (
                        <button
                          type="button"
                          className={button}
                          aria-label={`${props.scheduled ? "Remove" : "Cancel"} ${name}`}
                          disabled={cancel.isPending}
                          onClick={() => {
                            if (
                              !props.scheduled ||
                              window.confirm("Remove this scheduled output?")
                            )
                              cancel.mutate(job.id);
                          }}
                        >
                          {props.scheduled ? "Remove" : "Cancel"}
                        </button>
                      )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {pages > 1 && (
        <nav aria-label="Pages" className="flex items-center gap-2 text-sm">
          <button
            type="button"
            className={button}
            disabled={page <= 1}
            onClick={() => {
              setPage(page - 1);
            }}
          >
            Previous
          </button>
          <span>
            Page {page} of {pages}
          </span>
          <button
            type="button"
            className={button}
            disabled={page >= pages}
            onClick={() => {
              setPage(page + 1);
            }}
          >
            Next
          </button>
        </nav>
      )}
    </div>
  );
}
