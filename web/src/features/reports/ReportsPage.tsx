/**
 * `/reports` (screens.md): the stock reports, the user's own and shared layouts, a preview pane,
 * and PDF or email through the Outputs page (M7.4; use testing U-M7-2).
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "@/lib/api/client";
import {
  failure,
  hasPermission,
  meQuery,
  problemText,
} from "@/lib/auth/session";

import {
  layoutsQuery,
  previewHtml,
  templatesQuery,
  useDeleteLayout,
  asLayout,
  useSaveLayout,
} from "./api";

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
  const me = useQuery(meQuery).data;
  const canOutput = hasPermission(me, "outputs.pdf");
  const templates = useQuery({
    ...templatesQuery,
    enabled: hasPermission(me, "reports.print"),
  });
  const copy = useMutation({
    mutationFn: async (key: string) => {
      const result = await api.POST("/reports/templates/{key}/instantiate", {
        params: { path: { key } },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSuccess: (made) =>
      navigate({ to: "/reports/$id", params: { id: made.id } }),
  });
  const [preview, setPreview] = useState<{ name: string; html: string } | null>(
    null,
  );
  const [previewError, setPreviewError] = useState<unknown>(null);
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
      {(create.isError ||
        remove.isError ||
        copy.isError ||
        previewError !== null) && (
        <p role="alert">
          {problemText(
            create.error ?? remove.error ?? copy.error ?? previewError,
            "The change could not be saved.",
          )}
        </p>
      )}
      {templates.data && templates.data.length > 0 && (
        <section
          aria-labelledby="stock-heading"
          className="flex flex-col gap-2"
        >
          <h2 id="stock-heading" className="text-lg font-semibold">
            Stock reports
          </h2>
          <ul className="grid max-w-4xl gap-3 sm:grid-cols-2">
            {templates.data.map((t) => (
              <li
                key={t.key}
                className="flex flex-col gap-2 rounded border border-border p-3"
              >
                <h3 className="font-semibold">{t.label}</h3>
                {t.description && (
                  <p className="text-sm text-text-muted">{t.description}</p>
                )}
                <div className="flex flex-wrap gap-2">
                  {canOutput && (
                    <Link
                      to="/outputs"
                      search={{ new: `t:${t.key ?? ""}` }}
                      className={button}
                      aria-label={`PDF or email of ${t.label ?? ""}`}
                    >
                      PDF or email
                    </Link>
                  )}
                  <button
                    type="button"
                    className={button}
                    aria-label={`Open a copy of ${t.label ?? ""} to edit`}
                    disabled={copy.isPending}
                    onClick={() => {
                      if (t.key) copy.mutate(t.key);
                    }}
                  >
                    Open a copy
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <h2 className="text-lg font-semibold">My and shared reports</h2>
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
                  <td className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className={button}
                      aria-label={`Preview ${l.name}`}
                      onClick={() => {
                        setPreviewError(null);
                        previewHtml(l.id).then((html) => {
                          setPreview({ name: l.name, html });
                        }, setPreviewError);
                      }}
                    >
                      Preview
                    </button>
                    {canOutput && (
                      <Link
                        to="/outputs"
                        search={{ new: `l:${l.id}` }}
                        className={button}
                        aria-label={`PDF or email of ${l.name}`}
                      >
                        PDF or email
                      </Link>
                    )}
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
      {preview && (
        <section
          aria-labelledby="preview-heading"
          className="flex flex-col gap-2"
        >
          <h2 id="preview-heading" className="text-lg font-semibold">
            Preview of {preview.name}
          </h2>
          <iframe
            title="Report preview"
            sandbox=""
            srcDoc={preview.html}
            className="h-[70vh] w-full max-w-4xl rounded border border-border bg-white"
          />
        </section>
      )}
    </section>
  );
}
