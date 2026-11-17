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
  type CaptureRun,
  type Source,
} from "./api";
import { SourceEditor } from "./SourceEditor";

const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

function when(value: string | null | undefined): string {
  return value ? value.replace("T", " ").slice(0, 16) + " UTC" : "—";
}

/** `/admin/sources` (screens.md): table with health, last and next run; editor; run history. */
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
          key={editing === "new" ? "new" : editing.id}
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
              <td>{s.enabled ? "enabled" : "disabled"}</td>
              <td className="flex gap-2">
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
          key={open.id}
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

  return (
    <section
      aria-labelledby="runs-heading"
      className="flex flex-col gap-3 rounded border border-border p-3"
    >
      <h2 id="runs-heading" className="text-xl font-semibold">
        {source.name}: health and runs
      </h2>
      {health.data && (
        <p role="status">
          Health {health.data.health} · {health.data.runs_7d} runs in 7 days ·{" "}
          {Math.round((health.data.success_rate_7d ?? 0) * 100)}% succeeded
          {health.data.last_error
            ? ` · last error: ${health.data.last_error}`
            : ""}
        </p>
      )}
      {canManage && (
        <div className="flex gap-2">
          <button
            type="button"
            className={button}
            disabled={!source.enabled || !jobId || runNow.isPending}
            onClick={() => {
              runNow.mutate(jobId);
            }}
          >
            Run now
          </button>
          {source.enabled && (
            <button
              type="button"
              className={button}
              disabled={disable.isPending}
              onClick={() => {
                disable.mutate(source.id, { onSuccess: onClose });
              }}
            >
              Disable source
            </button>
          )}
          <button type="button" className={button} onClick={onClose}>
            Close
          </button>
        </div>
      )}
      {runNow.isSuccess && <p role="status">Run queued.</p>}
      {(runNow.isError || disable.isError) && (
        <p role="alert" className="text-critical">
          {problemText(runNow.error ?? disable.error, "The action failed.")}
        </p>
      )}
      {runs.data && <RunTable runs={runs.data.items} />}
    </section>
  );
}

function RunTable({ runs }: { runs: CaptureRun[] }) {
  if (runs.length === 0) return <p>No runs yet.</p>;
  return (
    <table className="w-full border-collapse text-left">
      <caption className="sr-only">Runs, newest first</caption>
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
                  {REASONS[r.error_class] ?? r.error_message}
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
