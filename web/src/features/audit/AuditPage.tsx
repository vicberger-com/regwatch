import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { failure, problemText } from "@/lib/auth/session";

type Entry = Schemas["AuditEntry"];
interface Filters {
  action?: string;
  entity_type?: string;
  from?: string;
  to?: string;
}
const PAGE_SIZE = 50;
const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

function auditQuery(filters: Filters, page: number) {
  return {
    queryKey: ["admin", "audit", filters, page],
    queryFn: async () => {
      const result = await api.GET("/admin/audit", {
        params: { query: { ...filters, page, page_size: PAGE_SIZE } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    placeholderData: keepPreviousData,
  };
}

/** A date input's value (YYYY-MM-DD) as the start of that day in UTC, for the API. */
function dayStart(value: string): string | undefined {
  return value ? `${value}T00:00:00Z` : undefined;
}

/** `/admin/audit` (screens.md): filterable table with before and after values. */
export function AuditPage() {
  const [draft, setDraft] = useState({
    action: "",
    entity_type: "",
    from: "",
    to: "",
  });
  const [filters, setFilters] = useState<Filters>({});
  const [page, setPage] = useState(1);
  const audit = useQuery(auditQuery(filters, page));

  function apply(event: FormEvent) {
    event.preventDefault();
    const next: Filters = {};
    if (draft.action.trim()) next.action = draft.action.trim();
    if (draft.entity_type.trim()) next.entity_type = draft.entity_type.trim();
    const from = dayStart(draft.from);
    if (from) next.from = from;
    const to = dayStart(draft.to);
    if (to) next.to = to;
    setFilters(next);
    setPage(1);
  }

  const total = audit.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const text = (key: keyof typeof draft, label: string, type = "text") => (
    <label className="flex flex-col gap-1">
      <span>{label}</span>
      <input
        type={type}
        value={draft[key]}
        onChange={(e) => {
          setDraft({ ...draft, [key]: e.target.value });
        }}
        className={field}
      />
    </label>
  );

  return (
    <section aria-labelledby="audit-heading" className="flex flex-col gap-4">
      <h1 id="audit-heading" className="text-2xl font-semibold">
        Audit log
      </h1>
      <form
        onSubmit={apply}
        aria-label="Filter audit log"
        className="flex flex-wrap items-end gap-3"
      >
        {text("action", "Action")}
        {text("entity_type", "Entity type")}
        {text("from", "From (UTC day)", "date")}
        {text("to", "Before (UTC day)", "date")}
        <button type="submit" className={button}>
          Apply filters
        </button>
      </form>
      {audit.isError && (
        <p role="alert" className="text-critical">
          {problemText(audit.error, "The audit log could not be loaded.")}
        </p>
      )}
      {audit.isPending ? (
        <p>Loading audit log…</p>
      ) : audit.data && !audit.isError ? (
        <>
          <p role="status">
            {total} entries · page {page} of {pages}
          </p>
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">Audit entries</caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col">When (UTC)</th>
                <th scope="col">Actor</th>
                <th scope="col">Action</th>
                <th scope="col">Entity</th>
                <th scope="col">Before</th>
                <th scope="col">After</th>
              </tr>
            </thead>
            <tbody>
              {audit.data.items.map((e) => (
                <Row key={e.id} entry={e} />
              ))}
            </tbody>
          </table>
          <div className="flex gap-2">
            <button
              type="button"
              className={button}
              disabled={page <= 1 || audit.isFetching}
              onClick={() => {
                setPage(page - 1);
              }}
            >
              Previous page
            </button>
            <button
              type="button"
              className={button}
              disabled={page >= pages || audit.isFetching}
              onClick={() => {
                setPage(page + 1);
              }}
            >
              Next page
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}

function Row({ entry }: { entry: Entry }) {
  return (
    <tr className="border-b border-border align-top">
      <td>{entry.occurred_at?.replace("T", " ").slice(0, 19)}</td>
      <td>{entry.actor_email ?? "system"}</td>
      <td>
        <code>{entry.action}</code>
      </td>
      <td>
        {entry.entity_type}
        {entry.entity_id ? (
          <code className="block text-text-muted">{entry.entity_id}</code>
        ) : null}
      </td>
      <td>
        <Value value={entry.before} />
      </td>
      <td>
        <Value value={entry.after} />
      </td>
    </tr>
  );
}

// One value shows at most this many characters, so a page of large rows stays usable.
export const VALUE_MAX = 10_000;

/** Before and after values as indented JSON text (rendered as text, never as markup). */
function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined)
    return <span className="text-text-muted">none</span>;
  const text = JSON.stringify(value, null, 2);
  const cut = text.length > VALUE_MAX;
  return (
    <pre className="max-w-md overflow-x-auto whitespace-pre-wrap text-xs">
      {cut ? text.slice(0, VALUE_MAX) : text}
      {cut && `\n… ${String(text.length - VALUE_MAX)} more characters`}
    </pre>
  );
}
