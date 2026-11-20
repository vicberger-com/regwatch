import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { problemText } from "@/lib/auth/session";

import {
  healthQuery,
  PAGE_SIZE,
  REASONS,
  runsQuery,
  sourcesQuery,
  useDisableSource,
  useRunNow,
  useTestSource,
  type CaptureRun,
  type Source,
  type SourceTestResult,
} from "./api";
import { RequestQueue } from "./FeedRequests";
import { SourceEditor } from "./SourceEditor";

const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

function when(value: string | null | undefined): string {
  return value ? value.replace("T", " ").slice(0, 16) + " UTC" : "—";
}

/** `/admin/sources` (screens.md): table with health, last and next run; editor; run history. */
/** Enabled, or captured because users follow it (CP-25): a followed catalogue source is
 * fetched while it shows enabled: false, so admins see that it is (11.2a review). */
export function sourceState(s: {
  enabled: boolean;
  captured?: boolean;
  followers?: number;
  catalogue_key?: string | null;
  job?: { enabled?: boolean };
}): string {
  if (s.enabled) return "enabled";
  const followers = s.followers ?? 0;
  if (s.captured)
    return `captured: followed by ${String(followers)} ${followers === 1 ? "user" : "users"}`;
  if (s.catalogue_key && s.job?.enabled !== false)
    return "catalogue, not followed";
  return "disabled";
}

export function SourcesPage({
  canManage,
  canOverride,
}: {
  canManage: boolean;
  canOverride: boolean;
}) {
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Source | "new" | null>(null);
  const [open, setOpen] = useState<Source | null>(null);
  const list = useQuery(sourcesQuery(page));

  if (list.isPending) return <p>Loading sources…</p>;
  if (list.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(list.error, "The sources could not be loaded.")}
      </p>
    );
  }
  const pages = Math.max(1, Math.ceil(list.data.total / PAGE_SIZE));
  return (
    <section aria-labelledby="src-heading" className="flex flex-col gap-4">
      <h1 id="src-heading" className="text-2xl font-semibold">
        Sources
      </h1>
      {canManage && <RequestQueue />}
      {canManage && (
        <div>
          <button
            type="button"
            className={button}
            onClick={() => {
              setEditing("new");
            }}
          >
            Create source
          </button>
        </div>
      )}
      {editing && (
        <SourceEditor
          key={editing === "new" ? "edit-new" : `edit-${editing.id}`}
          current={editing === "new" ? null : editing}
          canOverride={canOverride}
          onDone={() => {
            setEditing(null);
          }}
        />
      )}
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">Sources, {list.data.total} in all</caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col">Name</th>
            <th scope="col">Kind</th>
            <th scope="col">Health</th>
            <th scope="col">Last run</th>
            <th scope="col">Next run</th>
            <th scope="col">State</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {list.data.items.map((s) => (
            <tr key={s.id} className="border-b border-border">
              <td>{s.name}</td>
              <td>{s.kind}</td>
              <td>{s.health}</td>
              <td>{when(s.job?.last_run_at)}</td>
              <td>{when(s.job?.next_run_at)}</td>
              <td>{sourceState(s)}</td>
              <td>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className={button}
                    aria-label={`Runs and health of ${s.name}`}
                    onClick={() => {
                      setOpen(open?.id === s.id ? null : s);
                    }}
                  >
                    Runs
                  </button>
                  {canManage && (
                    <button
                      type="button"
                      className={button}
                      aria-label={`Edit ${s.name}`}
                      onClick={() => {
                        setEditing(s);
                      }}
                    >
                      Edit
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {pages > 1 && (
        <div className="flex gap-2">
          <button
            type="button"
            className={button}
            disabled={page <= 1}
            onClick={() => {
              setPage(page - 1);
            }}
          >
            Previous page
          </button>
          <button
            type="button"
            className={button}
            disabled={page >= pages}
            onClick={() => {
              setPage(page + 1);
            }}
          >
            Next page
          </button>
        </div>
      )}
      {open && (
        <SourceRuns
          key={`runs-${open.id}`}
          source={open}
          canManage={canManage}
          onClose={() => {
            setOpen(null);
          }}
        />
      )}
    </section>
  );
}

function SourceRuns({
  source,
  canManage,
  onClose,
}: {
  source: Source;
  canManage: boolean;
  onClose: () => void;
}) {
  const jobId = source.job?.id ?? "";
  const health = useQuery({
    ...healthQuery(source.id),
    enabled: Boolean(source.id),
  });
  const runs = useQuery({ ...runsQuery(jobId), enabled: Boolean(jobId) });
  const runNow = useRunNow();
  const disable = useDisableSource();
  const test = useTestSource();

  function act(action: "run" | "disable") {
    // One error at a time, from the action just taken (review finding 11).
    runNow.reset();
    disable.reset();
    test.reset();
    if (action === "run") runNow.mutate(jobId);
    else if (
      window.confirm(
        `Disable ${source.name}? It stops capturing; its items are kept.`,
      )
    )
      disable.mutate(source.id, { onSuccess: onClose });
  }

  return (
    <section
      aria-labelledby="runs-heading"
      className="flex flex-col gap-3 rounded border border-border p-3"
    >
      <h2 id="runs-heading" className="text-xl font-semibold">
        {source.name}: health and runs
      </h2>
      {health.isPending && <p>Loading health…</p>}
      {health.isError && (
        <p role="alert" className="text-critical">
          {problemText(health.error, "The health could not be loaded.")}
        </p>
      )}
      {health.data && (
        // Plain text, not a live region: it holds untrusted error text and refreshes.
        <p>
          Health {health.data.health} · {health.data.runs_7d} runs in 7 days ·{" "}
          {Math.round((health.data.success_rate_7d ?? 0) * 100)}% succeeded
          {health.data.last_error
            ? ` · last error: ${health.data.last_error}`
            : ""}
        </p>
      )}
      <div className="flex gap-2">
        {canManage && (
          <button
            type="button"
            className={button}
            disabled={
              !(source.enabled || source.captured) || !jobId || runNow.isPending
            }
            onClick={() => {
              act("run");
            }}
          >
            Run now
          </button>
        )}
        {canManage && (
          <button
            type="button"
            className={button}
            disabled={test.isPending}
            onClick={() => {
              runNow.reset();
              disable.reset();
              test.mutate(source.id);
            }}
          >
            {test.isPending ? "Testing…" : "Test"}
          </button>
        )}
        {canManage && source.enabled && (
          <button
            type="button"
            className={button}
            disabled={disable.isPending}
            onClick={() => {
              act("disable");
            }}
          >
            Disable source
          </button>
        )}
        <button type="button" className={button} onClick={onClose}>
          Close
        </button>
      </div>
      {/* Present before it is filled, so screen readers announce the change. */}
      <p role="status">{runNow.isSuccess ? "Run queued." : ""}</p>
      {test.isError && (
        <p role="alert" className="text-critical">
          {problemText(test.error, "The test failed.")}
        </p>
      )}
      {test.data && <TestResult result={test.data} />}
      {(runNow.isError || disable.isError) && (
        <p role="alert" className="text-critical">
          {problemText(runNow.error ?? disable.error, "The action failed.")}
        </p>
      )}
      {runs.isPending && jobId && <p>Loading runs…</p>}
      {runs.isError && (
        <p role="alert" className="text-critical">
          {problemText(runs.error, "The runs could not be loaded.")}
        </p>
      )}
      {runs.data && <RunTable runs={runs.data.items} total={runs.data.total} />}
    </section>
  );
}

function reason(
  errorClass: string,
  message: string | null | undefined,
): string {
  // An own-property lookup: a class such as "__proto__" or "toString" is not a reason (13).
  return Object.hasOwn(REASONS, errorClass)
    ? (REASONS[errorClass] ?? "")
    : (message ?? "");
}

function TestResult({ result }: { result: SourceTestResult }) {
  return (
    <section aria-labelledby="test-heading" className="flex flex-col gap-1">
      <h3 id="test-heading" className="font-semibold">
        Test: first candidates (robots.txt {result.robots_decision ?? "unknown"}
        )
      </h3>
      {(result.warnings ?? []).map((w) => (
        <p key={w} className="text-warning">
          {w}
        </p>
      ))}
      <ul className="list-disc pl-5">
        {(result.candidates ?? []).map((c) => (
          // Text only: a candidate's title and address come from the source and are untrusted.
          <li key={c.url}>
            {c.title ?? "(no title)"}{" "}
            <code className="text-text-muted">{c.url}</code>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RunTable({ runs, total }: { runs: CaptureRun[]; total: number }) {
  if (runs.length === 0) return <p>No runs yet.</p>;
  return (
    <table className="w-full border-collapse text-left">
      <caption className="sr-only">
        Runs, newest first: {runs.length} of {total}
      </caption>
      <thead>
        <tr className="border-b border-border">
          <th scope="col">Started</th>
          <th scope="col">Status</th>
          <th scope="col">New</th>
          <th scope="col">Bytes</th>
          <th scope="col">robots.txt</th>
          <th scope="col">Why</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => (
          <tr key={r.id} className="border-b border-border align-top">
            <td>{when(r.started_at)}</td>
            <td>{r.status}</td>
            <td>{r.items_new}</td>
            <td>{r.bytes_fetched}</td>
            <td>{r.robots_decision ?? "—"}</td>
            <td>
              {r.error_class ? (
                <>
                  <code>{r.error_class}</code>{" "}
                  {reason(r.error_class, r.error_message)}
                </>
              ) : (
                (r.error_message ?? "")
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
