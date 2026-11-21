/**
 * `/reports/$id`: page settings, the data source and the Puck editor (lazy-loaded), with the
 * server-rendered preview in a sandboxed frame (M7.4). The server validates every save.
 */
import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useId, useState } from "react";

import { viewsQuery } from "@/features/me/api";
import { defaults, ParamFields, type Params } from "./ParamFields";
import { problemText } from "@/lib/auth/session";

import {
  fieldsQuery,
  layoutQuery,
  previewUrl,
  templatesQuery,
  useSaveLayout,
  asLayout,
  type ReportLayout,
} from "./api";

const Editor = lazy(() => import("./Editor"));
const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

function Settings({
  layout,
  userId,
  canShare,
}: {
  layout: ReportLayout;
  userId: string;
  canShare: boolean;
}) {
  const id = useId();
  const fields = useQuery(fieldsQuery);
  const views = useQuery(viewsQuery);
  const save = useSaveLayout();
  const mine = layout.user_id === userId;
  const [name, setName] = useState(layout.name);
  const [pageSize, setPageSize] = useState(layout.page_size);
  const [orientation, setOrientation] = useState(layout.orientation);
  const [shared, setShared] = useState(layout.shared);
  const [viewId, setViewId] = useState(layout.data_source?.saved_view_id ?? "");
  const [words, setWords] = useState(layout.data_source?.query?.q ?? "");
  const [limit, setLimit] = useState(layout.data_source?.limit ?? 500);
  const [data, setData] = useState<Record<string, unknown>>(layout.layout);
  const [preview, setPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<unknown>(null);
  // A layout made from a stock report previews with that report's settings (U-M7-1).
  const templates = useQuery({
    ...templatesQuery,
    enabled: Boolean(layout.based_on_template_key),
  });
  const defs = templates.data?.find(
    (t) => t.key === layout.based_on_template_key,
  )?.parameters;
  const [params, setParams] = useState<Params | null>(null);
  const values = params ?? defaults(defs);

  const body = {
    name,
    page_size: pageSize,
    orientation,
    shared,
    layout: asLayout(data),
    data_source: viewId
      ? { saved_view_id: viewId, limit }
      : {
          query: {
            ...(words.trim() ? { q: words.trim() } : {}),
            sort: "last_changed_desc" as const,
            page: 1,
            page_size: 50,
            highlight: false,
            facet_counts: false,
          },
          limit,
        },
  };
  return (
    <div className="grid gap-4">
      <form
        aria-label="Report settings"
        className="grid max-w-3xl gap-2 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ id: layout.id, body });
        }}
      >
        <label htmlFor={`${id}-name`} className="text-sm">
          Name
        </label>
        <input
          id={`${id}-name`}
          required
          maxLength={120}
          className={field}
          value={name}
          disabled={!mine}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
        <label htmlFor={`${id}-size`} className="text-sm">
          Page size
        </label>
        <select
          id={`${id}-size`}
          className={field}
          value={pageSize}
          disabled={!mine}
          onChange={(e) => {
            setPageSize(e.target.value as typeof pageSize);
          }}
        >
          <option value="A4">A4</option>
          <option value="Letter">Letter</option>
        </select>
        <label htmlFor={`${id}-orient`} className="text-sm">
          Orientation
        </label>
        <select
          id={`${id}-orient`}
          className={field}
          value={orientation}
          disabled={!mine}
          onChange={(e) => {
            setOrientation(e.target.value as typeof orientation);
          }}
        >
          <option value="portrait">Portrait</option>
          <option value="landscape">Landscape</option>
        </select>
        <label htmlFor={`${id}-view`} className="text-sm">
          Data: saved view
        </label>
        <select
          id={`${id}-view`}
          className={field}
          value={viewId}
          disabled={!mine}
          onChange={(e) => {
            setViewId(e.target.value);
          }}
        >
          <option value="">None: use the search words below</option>
          {(views.data ?? []).map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
              {v.shared ? " (shared)" : ""}
            </option>
          ))}
        </select>
        <label htmlFor={`${id}-words`} className="text-sm">
          Data: search words
        </label>
        <input
          id={`${id}-words`}
          maxLength={500}
          className={field}
          value={words}
          disabled={!mine || Boolean(viewId)}
          onChange={(e) => {
            setWords(e.target.value);
          }}
        />
        <label htmlFor={`${id}-limit`} className="text-sm">
          Most items (1 to 5,000; previews read 500)
        </label>
        <input
          id={`${id}-limit`}
          type="number"
          min={1}
          max={5000}
          className={field}
          value={limit}
          disabled={!mine}
          onChange={(e) => {
            setLimit(Number(e.target.value));
          }}
        />
        {canShare && mine && (
          <label className="flex min-h-6 items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              className="h-5 w-5"
              checked={shared}
              onChange={(e) => {
                setShared(e.target.checked);
              }}
            />
            Share with everyone who builds reports (a shared report needs a
            shared saved view, or search words)
          </label>
        )}
        <div className="sm:col-span-2">
          <ParamFields defs={defs} values={values} onChange={setParams} />
        </div>
        <div className="flex gap-2 sm:col-span-2">
          {mine && (
            <button type="submit" className={button} disabled={save.isPending}>
              Save
            </button>
          )}
          <button
            type="button"
            className={button}
            onClick={() => {
              setPreviewError(null);
              previewUrl(layout.id, defs && defs.length > 0 ? values : {}).then(
                setPreview,
                setPreviewError,
              );
            }}
          >
            Preview the saved version
          </button>
        </div>
        <p role="status" className="text-sm text-text-muted sm:col-span-2">
          {save.isSuccess ? `Saved: version ${String(save.data.version)}.` : ""}
        </p>
        {(save.isError || previewError !== null) && (
          <p role="alert" className="sm:col-span-2">
            {problemText(save.error ?? previewError, "That did not work.")}
          </p>
        )}
      </form>
      {fields.data && mine && (
        <Suspense fallback={<p>Loading the editor…</p>}>
          <Editor
            fields={fields.data}
            data={layout.layout}
            onChange={setData}
          />
        </Suspense>
      )}
      {preview !== null && (
        // The server's HTML holds captured text: no scripts and no same-origin access.
        <iframe
          title="Report preview"
          sandbox=""
          src={preview}
          className="h-[70vh] w-full max-w-4xl rounded border border-border bg-white"
        />
      )}
    </div>
  );
}

export function BuilderPage(props: {
  id: string;
  userId: string;
  canShare: boolean;
}) {
  const layout = useQuery(layoutQuery(props.id));
  if (layout.isPending) return <p>Loading the report…</p>;
  if (layout.isError)
    return (
      <p role="alert" className="text-critical">
        {problemText(layout.error, "The report could not be loaded.")}
      </p>
    );
  return (
    <section aria-labelledby="builder-heading" className="flex flex-col gap-4">
      <h1 id="builder-heading" className="text-2xl font-semibold">
        {layout.data.name}
      </h1>
      <Settings
        key={
          layout.data.id
        } /* not the version: a save must not remount the editor */
        layout={layout.data}
        userId={props.userId}
        canShare={props.canShare}
      />
    </section>
  );
}
