/** `/reports` (screens.md): the user's own and shared report layouts (M7.4). */
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";

import { problemText } from "@/lib/auth/session";

import { layoutsQuery, useDeleteLayout, asLayout, useSaveLayout } from "./api";

const button = "rounded border border-border px-2 py-1 disabled:opacity-50";
const BLANK = {
  root: { props: { title: "" } },
  content: [
    {
      type: "Heading",
      props: { id: "heading-1", text: "New report", level: 1 },
    },
    {
      type: "ItemsTable",
      props: {
        id: "table-1",
        columns: ["item.title", "jurisdiction.names", "item.last_changed_at"],
        sort: "item.last_changed_at",
        direction: "desc",
        limit: 50,
      },
    },
  ],
};

export function ReportsPage({ userId }: { userId: string }) {
  const layouts = useQuery(layoutsQuery);
  const create = useSaveLayout();
  const remove = useDeleteLayout();
  const navigate = useNavigate();
  if (layouts.isPending) return <p>Loading reports…</p>;
  if (layouts.isError)
    return (
      <p role="alert" className="text-critical">
        {problemText(layouts.error, "The reports could not be loaded.")}
      </p>
    );
  return (
    <section aria-labelledby="reports-heading" className="flex flex-col gap-4">
      <h1 id="reports-heading" className="text-2xl font-semibold">
        Reports
      </h1>
      <div>
        <button
          type="button"
          className={button}
          disabled={create.isPending}
          onClick={() => {
            create.mutate(
              {
                body: {
                  name: "New report",
                  layout: asLayout(BLANK),
                },
              },
              {
                onSuccess: (saved) => {
                  void navigate({
                    to: "/reports/$id",
                    params: { id: saved.id },
                  });
                },
              },
            );
          }}
        >
          New report
        </button>
      </div>
      {(create.isError || remove.isError) && (
        <p role="alert">
          {problemText(
            create.error ?? remove.error,
            "The change could not be saved.",
          )}
        </p>
      )}
      {layouts.data.length === 0 ? (
        <p className="text-sm text-text-muted">No reports yet.</p>
      ) : (
        <table className="w-full max-w-3xl text-sm">
          <thead>
            <tr>
              <th scope="col" className="text-left">
                Name
              </th>
              <th scope="col" className="text-left">
                Owner
              </th>
              <th scope="col" className="text-left">
                Version
              </th>
              <th scope="col" className="text-left">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {layouts.data.map((l) => {
              const mine = l.user_id === userId;
              return (
                <tr key={l.id}>
                  <td>
                    <Link
                      to="/reports/$id"
                      params={{ id: l.id }}
                      className="text-accent underline"
                    >
                      {l.name}
                    </Link>
                  </td>
                  <td>
                    {mine ? "You" : "Shared"}
                    {mine && l.shared ? " (shared)" : ""}
                  </td>
                  <td>{l.version}</td>
                  <td>
                    {mine && (
                      <button
                        type="button"
                        className={button}
                        aria-label={`Delete ${l.name}`}
                        disabled={remove.isPending}
                        onClick={() => {
                          if (window.confirm(`Delete the report ${l.name}?`))
                            remove.mutate(l.id);
                        }}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
