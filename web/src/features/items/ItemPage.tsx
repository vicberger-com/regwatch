import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { jurisdictionName } from "@/features/map/names";
import { problemText } from "@/lib/auth/session";

import { itemQuery } from "./api";

const date = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString() : "—";

/** A link to the item's own page, only when it is an http(s) URL (captured data is hostile). */
export function safeUrl(url: string | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

/** `/items/:id`: the item's header and summary (screens.md); versions and the diff follow. */
export function ItemPage({ id }: { id: string }) {
  const item = useQuery(itemQuery(id));
  if (item.isPending) return <p role="status">Loading the item…</p>;
  if (item.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(item.error, "The item could not be loaded.")}
      </p>
    );
  }
  const data = item.data;
  const source = safeUrl(data.canonical_url);
  return (
    <article>
      <p>
        <Link
          to="/items"
          className="text-sm text-accent underline-offset-2 hover:underline"
        >
          Back to items
        </Link>
      </p>
      <h1
        className="mt-2 text-2xl font-semibold"
        lang={data.language ?? undefined}
      >
        {data.title}
      </h1>
      {data.title_en && data.title_en !== data.title && (
        <p className="text-text-muted" lang="en">
          {data.title_en}
        </p>
      )}
      <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1">
        <dt className="text-text-muted">Jurisdictions</dt>
        <dd>
          {data.jurisdictions
            .map((j) => (j.code ? jurisdictionName(j.code) : ""))
            .filter(Boolean)
            .join(", ") || "—"}
        </dd>
        <dt className="text-text-muted">Source</dt>
        <dd>
          {data.source_name ?? "—"}
          {source && (
            <>
              {" · "}
              <a
                href={source}
                rel="noopener noreferrer nofollow"
                target="_blank"
                className="text-accent underline"
              >
                Original page (opens in a new tab)
              </a>
            </>
          )}
        </dd>
        <dt className="text-text-muted">Status</dt>
        <dd>{data.status}</dd>
        <dt className="text-text-muted">Severity</dt>
        <dd>{data.severity ?? "—"}</dd>
        <dt className="text-text-muted">Published</dt>
        <dd>{date(data.published_at)}</dd>
        <dt className="text-text-muted">Last changed</dt>
        <dd>{date(data.last_changed_at)}</dd>
      </dl>
      <h2 className="mt-6 text-lg font-semibold">Summary</h2>
      <p className="mt-2 whitespace-pre-line" lang={data.language ?? undefined}>
        {data.summary ?? "No summary."}
      </p>
      {data.summary_en && data.summary_en !== data.summary && (
        <p className="mt-2 whitespace-pre-line text-text-muted" lang="en">
          {data.summary_en}
        </p>
      )}
    </article>
  );
}
