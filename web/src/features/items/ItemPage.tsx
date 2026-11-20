import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "@tanstack/react-router";

import { jurisdictionName } from "@/features/map/names";
import { problemText } from "@/lib/auth/session";

import { diffQuery, itemQuery, versionsQuery, type ItemDetail } from "./api";
import { DiffView } from "./DiffView";
import { Tabs } from "./Tabs";
import { formatDateTime } from "@/lib/time/format";

const date = (value: string | null | undefined) =>
  value ? formatDateTime(value) : "—";

/** A link to the item's own page, only when it is an http(s) URL (captured data is hostile). */
export function safeUrl(url: string | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:")
      return null;
    return parsed.username || parsed.password ? null : parsed.href; // no credentials in links
  } catch {
    return null;
  }
}

/** `/items/:id` (screens.md): the item's header, then Summary, Content, Versions and Diff tabs. */
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
                Original page on {new URL(source).hostname} (opens in a new tab)
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
      <div className="mt-6">
        <ItemTabs item={data} />
      </div>
    </article>
  );
}

function ItemTabs({ item }: { item: ItemDetail }) {
  const [tab, setTab] = useState("summary");
  const [diff, setDiff] = useState<{ from: number; to: number } | null>(null);
  return (
    <Tabs
      label="Item"
      active={tab}
      onChange={setTab}
      tabs={[
        {
          id: "summary",
          label: "Summary",
          panel: () => <Summary item={item} />,
        },
        {
          id: "content",
          label: "Content",
          panel: () => <Content item={item} />,
        },
        {
          id: "versions",
          label: "Versions",
          panel: () => (
            <Versions
              id={item.id}
              onCompare={(from, to) => {
                setDiff({ from, to });
                setTab("diff");
              }}
            />
          ),
        },
        {
          id: "diff",
          label: "Diff",
          panel: () => <Diff item={item} chosen={diff} onChoose={setDiff} />,
        },
      ]}
    />
  );
}

function Summary({ item }: { item: ItemDetail }) {
  return (
    <>
      <p className="whitespace-pre-line" lang={item.language ?? undefined}>
        {item.summary ?? "No summary."}
      </p>
      {item.summary_en && item.summary_en !== item.summary && (
        <p className="mt-2 whitespace-pre-line text-text-muted" lang="en">
          {item.summary_en}
        </p>
      )}
      <h2 className="mt-4 font-semibold">Tags</h2>
      {item.terms?.length ? (
        <ul className="mt-1 flex flex-wrap gap-2">
          {item.terms.map((t) => (
            <li
              key={`${t.facet_key ?? ""}:${t.key ?? ""}`}
              className="rounded border border-border px-2 py-0.5 text-sm"
            >
              {t.label ?? t.key}
              {t.confidence !== undefined && (
                <span className="text-text-muted">
                  {" "}
                  · {Math.round(t.confidence * 100)}%
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-text-muted">No tags.</p>
      )}
    </>
  );
}

function Content({ item }: { item: ItemDetail }) {
  const translated = Boolean(item.content_text_en);
  const [english, setEnglish] = useState(false);
  const text =
    english && item.content_text_en ? item.content_text_en : item.content_text;
  return (
    <>
      {translated && (
        <label className="mb-3 flex items-center gap-2">
          <input
            type="checkbox"
            checked={english}
            onChange={(e) => {
              setEnglish(e.target.checked);
            }}
          />
          Show the English translation
        </label>
      )}
      {text ? (
        <div
          className="max-w-prose whitespace-pre-wrap"
          lang={english ? "en" : (item.language ?? undefined)}
        >
          {text}
        </div>
      ) : (
        <p className="text-text-muted">No text was captured for this item.</p>
      )}
    </>
  );
}

/** At most this many versions are offered for comparison (a broken answer cannot hang the tab). */
const MAX_VERSIONS = 500;

/** The item's version numbers, newest first, from the versions list itself (gaps allowed). */
function useVersionNumbers(id: string) {
  const versions = useQuery(versionsQuery(id));
  const numbers = (versions.data ?? [])
    .map((v) => v.version_no)
    .filter((n): n is number => Number.isInteger(n) && (n ?? 0) > 0)
    .sort((a, b) => b - a)
    .slice(0, MAX_VERSIONS);
  return { versions, numbers };
}

function Versions({
  id,
  onCompare,
}: {
  id: string;
  onCompare: (from: number, to: number) => void;
}) {
  const { versions, numbers } = useVersionNumbers(id);
  if (versions.isPending) return <p role="status">Loading versions…</p>;
  if (versions.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(versions.error, "The versions could not be loaded.")}
      </p>
    );
  }
  const byNumber = new Map(versions.data.map((v) => [v.version_no, v]));
  return (
    <table className="w-full text-left">
      <caption className="mb-2 text-left text-sm text-text-muted">
        {String(numbers.length)} versions, newest first
      </caption>
      <thead>
        <tr className="border-b border-border">
          <th scope="col" className="py-1 pr-4">
            Version
          </th>
          <th scope="col" className="py-1 pr-4">
            Captured
          </th>
          <th scope="col" className="py-1 pr-4">
            Changed
          </th>
          <th scope="col" className="py-1">
            <span className="sr-only">Compare</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {numbers.map((n, i) => {
          const v = byNumber.get(n);
          const previous = numbers[i + 1]; // the previous version that exists
          return (
            <tr key={n} className="border-b border-border">
              <td className="py-1 pr-4">{String(n)}</td>
              <td className="py-1 pr-4">{date(v?.created_at)}</td>
              <td className="py-1 pr-4">
                {typeof v?.changed_pct === "number"
                  ? `${String(Math.round(v.changed_pct * 10) / 10)}%`
                  : "—"}
              </td>
              <td className="py-1">
                {previous !== undefined && (
                  <button
                    type="button"
                    className="text-accent underline"
                    onClick={() => {
                      onCompare(previous, n);
                    }}
                  >
                    Compare with version {String(previous)}
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Diff(props: {
  item: ItemDetail;
  chosen: { from: number; to: number } | null;
  onChoose: (c: { from: number; to: number }) => void;
}) {
  const { versions, numbers } = useVersionNumbers(props.item.id);
  const fallback =
    numbers.length >= 2 ? { from: numbers[1] ?? 0, to: numbers[0] ?? 0 } : null;
  const chosen = props.chosen ?? fallback;
  // The selects change a draft; one request goes out on Compare (the API limits diffs a minute).
  const [draft, setDraft] = useState<{ from: number; to: number } | null>(null);
  const shown = draft ?? chosen;
  const ready = chosen !== null && chosen.from < chosen.to;
  const diff = useQuery({
    ...diffQuery(props.item.id, chosen?.from ?? 0, chosen?.to ?? 0),
    enabled: ready,
  });
  if (versions.isPending) return <p role="status">Loading versions…</p>;
  if (versions.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(versions.error, "The versions could not be loaded.")}
      </p>
    );
  }
  if (!shown || numbers.length < 2) {
    return (
      <p className="text-text-muted">
        This item has one version, so there is nothing to compare.
      </p>
    );
  }
  const pick = (field: "from" | "to") => (
    <label className="flex flex-col text-sm">
      {field === "from" ? "From version" : "To version"}
      <select
        value={shown[field]}
        onChange={(e) => {
          setDraft({ ...shown, [field]: Number(e.target.value) });
        }}
        className="mt-1 rounded border border-border bg-surface px-2 py-1"
      >
        {numbers.map((n) => (
          <option key={n} value={n}>
            {String(n)}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <>
      <form
        aria-label="Versions to compare"
        className="mb-3 flex items-end gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (draft) props.onChoose(draft);
          setDraft(null);
        }}
      >
        {pick("from")}
        {pick("to")}
        <button
          type="submit"
          disabled={shown.from >= shown.to}
          className="rounded border border-border px-3 py-1 disabled:opacity-50"
        >
          Compare
        </button>
      </form>
      {shown.from >= shown.to ? (
        <p className="text-text-muted">Choose an earlier version first.</p>
      ) : !ready || diff.isPending ? (
        <p role="status">Loading the changes…</p>
      ) : diff.isError ? (
        <p role="alert" className="text-critical">
          {problemText(diff.error, "The changes could not be loaded.")}
        </p>
      ) : (
        <DiffView
          unified={diff.data.unified_diff ?? ""}
          label={`Version ${String(chosen.from)} to ${String(chosen.to)}`}
        />
      )}
    </>
  );
}
