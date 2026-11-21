/**
 * The items list's own actions (screens.md `/items`: Export CSV; use testing round 2):
 * - Save as view (U-M7-3): the list's search and filters as a saved view, which reports, CSV
 *   outputs and the map can use; shared too with `views.manage_shared`.
 * - Export CSV (U-M8-4): the list as it is filtered, through `POST /search/export.csv`
 *   (`outputs.csv`), downloaded at once.
 * The API checks every permission again.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { api, type Schemas } from "@/lib/api/client";
import {
  failure,
  hasPermission,
  meQuery,
  problemText,
} from "@/lib/auth/session";

type Query = Schemas["Query"];
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

export function ItemsActions(props: {
  query: Query;
  days: number | undefined;
}) {
  const id = useId();
  const me = useQuery(meQuery).data;
  const client = useQueryClient();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);

  const filters = Object.fromEntries(
    Object.entries(props.query.filters ?? {}).filter(([k]) => k !== "changed"),
  );
  const save = useMutation({
    mutationFn: async () => {
      const result = await api.POST("/views", {
        body: {
          name: name.trim(),
          ...(props.query.q ? { q: props.query.q } : {}),
          filters, // the period is kept as days, so the view stays current
          period_days: props.days ?? 30,
          shared,
        },
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSuccess: () => {
      setNaming(false);
      setName("");
      return client.invalidateQueries({ queryKey: ["views"] });
    },
  });
  const exportCsv = useMutation({
    mutationFn: async () => {
      const result = await api.POST("/search/export.csv", {
        body: { ...props.query, page: 1, page_size: 50 },
        parseAs: "blob",
      });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(result.data);
      link.download = `regwatch-items-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(link.href);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) save.mutate();
  };
  const failed = save.error ?? exportCsv.error;
  return (
    <div className="mt-2 flex flex-col gap-2 text-sm">
      <div className="flex flex-wrap gap-2">
        {hasPermission(me, "items.read") && (
          <button
            type="button"
            className={button}
            aria-expanded={naming}
            onClick={() => {
              setNaming(!naming);
            }}
          >
            Save as view
          </button>
        )}
        {hasPermission(me, "outputs.csv") && (
          <button
            type="button"
            className={button}
            disabled={exportCsv.isPending}
            onClick={() => {
              exportCsv.mutate();
            }}
          >
            {exportCsv.isPending ? "Exporting…" : "Export CSV"}
          </button>
        )}
      </div>
      {naming && (
        <form
          aria-labelledby={`${id}-title`}
          className="flex flex-wrap items-end gap-2"
          onSubmit={submit}
        >
          <h2 id={`${id}-title`} className="sr-only">
            Save as view
          </h2>
          <label className="flex flex-col">
            View name
            <input
              className="mt-1 rounded border border-border bg-surface px-2 py-1"
              required
              maxLength={200}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
              }}
            />
          </label>
          {hasPermission(me, "views.manage_shared") && (
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={shared}
                onChange={(e) => {
                  setShared(e.target.checked);
                }}
              />
              Share with everyone
            </label>
          )}
          <button type="submit" className={button} disabled={save.isPending}>
            Save
          </button>
        </form>
      )}
      <p role="status">
        {save.isSuccess &&
          `Saved the view ${save.data.name}. Reports, outputs and the map can use it.`}
      </p>
      {failed && (
        <p role="alert" className="text-critical">
          {problemText(failed, "That did not work.")}
        </p>
      )}
    </div>
  );
}
