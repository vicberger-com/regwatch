import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { interestFilters, type Filters } from "@/features/map/api";
import { jurisdictionName } from "@/features/map/names";
import {
  effectiveInterests,
  myGroupsQuery,
  preferencesQuery,
} from "@/features/me/api";
import { interestOptionsQuery } from "@/features/me/InterestsEditor";
import { problemText } from "@/lib/auth/session";

import { searchQuery, type ItemSummary, type Query } from "./api";
import { ItemsActions } from "./ItemsActions";
import { Marked } from "./Marked";
import { formatDate } from "@/lib/time/format";

export const PAGE_SIZE = 25;
export type Sort =
  "relevance" | "last_changed_desc" | "published_desc" | "title_asc";

export interface ItemsSearch {
  q?: string;
  /** Jurisdiction codes, comma-separated in the URL. */
  j?: string;
  /** Changed within the last this many days. */
  days?: number;
  /** One facet term, `facet:term` (the map's facet view). */
  t?: string;
  sort?: Sort;
  page?: number;
  /** Show everything instead of the user's interests (M11.1). */
  all?: boolean;
}

const SORTS: { value: Sort; label: string; column: string }[] = [
  {
    value: "last_changed_desc",
    label: "Last changed, newest first",
    column: "changed",
  },
  {
    value: "published_desc",
    label: "Published, newest first",
    column: "published",
  },
  { value: "title_asc", label: "Title, A to Z", column: "title" },
  { value: "relevance", label: "Relevance", column: "" },
];

/** The validated `/items` search parameters (TanStack Router `validateSearch`). */
export function parseItemsSearch(raw: Record<string, unknown>): ItemsSearch {
  const out: ItemsSearch = {};
  if (typeof raw.q === "string" && raw.q.trim()) out.q = raw.q.slice(0, 500);
  if (typeof raw.j === "string" && /^[A-Za-z0-9,_-]{1,400}$/.test(raw.j))
    out.j = raw.j.toUpperCase();
  if (
    typeof raw.t === "string" &&
    /^[a-z0-9_-]{1,64}:[a-z0-9_-]{1,64}$/.test(raw.t)
  )
    out.t = raw.t;
  const days = Number(raw.days);
  if (Number.isInteger(days) && days >= 1 && days <= 3660) out.days = days;
  if (SORTS.some((s) => s.value === raw.sort)) out.sort = raw.sort as Sort;
  const page = Number(raw.page);
  if (Number.isInteger(page) && page >= 1 && page <= 400) out.page = page;
  if (raw.all === true || raw.all === "1" || raw.all === 1) out.all = true;
  return out;
}

/** ``search`` without the given keys (a new search starts on page 1). */
function without(
  search: ItemsSearch,
  ...keys: (keyof ItemsSearch)[]
): ItemsSearch {
  return Object.fromEntries(
    Object.entries(search).filter(
      ([key]) => !keys.includes(key as keyof ItemsSearch),
    ),
  );
}

/** Interests apply when the address names no place or topic of its own and not "all". */
export function usesInterests(
  search: ItemsSearch,
  interests: Filters,
): boolean {
  return (
    !search.all && !search.j && !search.t && Object.keys(interests).length > 0
  );
}

export function toQuery(
  search: ItemsSearch,
  now = new Date(),
  interests: Filters = {},
): Query {
  const filters: NonNullable<Query["filters"]> = usesInterests(
    search,
    interests,
  )
    ? { ...interests }
    : {};
  if (search.j) filters.jurisdictions = search.j.split(",").filter(Boolean);
  if (search.t) {
    const [facet = "", term = ""] = search.t.split(":");
    filters.terms = { [facet]: [term] };
  }
  if (search.days) {
    filters.changed = {
      from: new Date(now.getTime() - search.days * 86_400_000).toISOString(),
    };
  }
  return {
    ...(search.q ? { q: search.q } : {}),
    filters,
    sort: search.sort ?? (search.q ? "relevance" : "last_changed_desc"),
    page: search.page ?? 1,
    page_size: PAGE_SIZE,
    highlight: Boolean(search.q),
    facet_counts: false,
  };
}

const date = (value: string | null | undefined) =>
  value ? formatDate(value) : "—";

function Title({ item }: { item: ItemSummary }) {
  const lit = item.highlights?.title?.[0];
  return (
    <>
      <Link
        to="/items/$id"
        params={{ id: item.id }}
        className="font-semibold text-accent underline-offset-2 hover:underline"
      >
        <bdi>
          {typeof lit === "string" ? <Marked html={lit} /> : item.title}
        </bdi>
      </Link>
      {item.title_en && item.title_en !== item.title && (
        <span className="block text-sm text-text-muted" lang="en">
          {item.title_en}
        </span>
      )}
    </>
  );
}

/** A removable chip for one active filter (M6: active filters as removable chips). */
function FilterChip(props: { label: string; onRemove: () => void }) {
  return (
    <li className="flex items-center gap-1 rounded border border-border bg-surface px-2 py-0.5">
      {props.label}
      <button
        type="button"
        onClick={props.onRemove}
        className="rounded px-1 hover:bg-bg"
      >
        <span aria-hidden="true">×</span>
        <span className="sr-only">Remove the filter {props.label}</span>
      </button>
    </li>
  );
}

/** `/items`: the items table (screens.md), driven by the URL so views can be linked. */
export function ItemsPage(props: {
  search: ItemsSearch;
  onSearch: (next: ItemsSearch) => void;
}) {
  const { search, onSearch } = props;
  const [text, setText] = useState(search.q ?? "");
  const [now] = useState(() => new Date()); // one "now" per visit keeps the query key stable
  const prefs = useQuery(preferencesQuery);
  const options = useQuery(interestOptionsQuery);
  const groups = useQuery(myGroupsQuery); // the page needs items.read already
  const effective = effectiveInterests(prefs.data?.interests, groups.data);
  const interests = interestFilters(effective.interests, options.data);
  const filteredTo = effective.group
    ? `Filtered to ${effective.group}'s interests`
    : "Filtered to my interests";
  const mine = usesInterests(search, interests);
  const result = useQuery({
    ...searchQuery(toQuery(search, now, interests)),
    placeholderData: keepPreviousData,
    // The first search knows the interests, the user's or their group's.
    enabled: !prefs.isPending && !options.isPending && !groups.isPending,
  });
  const sort = toQuery(search, now).sort;
  const page = search.page ?? 1;
  const total = result.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const rest = without(search, "q", "page");
    onSearch(text.trim() ? { ...rest, q: text.trim() } : rest);
  };
  const ariaSort = (column: string) =>
    SORTS.find((s) => s.value === sort)?.column === column
      ? column === "title"
        ? "ascending"
        : "descending"
      : undefined;
  // SearchResult narrows Page.items to ItemSummary; the generated intersection keeps unknown.
  const items = (result.data?.items ?? []) as ItemSummary[];
  const caption = result.isPending
    ? "Loading items…"
    : `${String(total)}${total >= 10_000 ? "+" : ""} ${total === 1 ? "item" : "items"}`;

  return (
    <>
      <h1 className="text-2xl font-semibold">Items</h1>
      <form
        role="search"
        onSubmit={submit}
        className="mt-4 flex flex-wrap items-end gap-2"
      >
        <label className="flex flex-col text-sm">
          Search items
          <input
            type="search"
            value={text}
            maxLength={500}
            onChange={(e) => {
              setText(e.target.value);
            }}
            className="mt-1 w-96 max-w-full rounded border border-border bg-surface px-2 py-1"
          />
        </label>
        <button
          type="submit"
          className="rounded bg-accent px-3 py-1 text-accent-contrast"
        >
          Search
        </button>
        <label className="ml-4 flex flex-col text-sm">
          Sort
          <select
            value={sort}
            onChange={(e) => {
              onSearch({
                ...without(search, "page"),
                sort: e.target.value as Sort,
              });
            }}
            className="mt-1 rounded border border-border bg-surface px-2 py-1"
          >
            {SORTS.filter((s) => s.value !== "relevance" || search.q).map(
              (s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ),
            )}
          </select>
        </label>
      </form>
      <ItemsActions
        query={toQuery(search, now, interests)}
        days={search.days}
      />
      {(mine || search.all) && Object.keys(interests).length > 0 && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded border border-accent px-2 py-0.5">
            {mine ? filteredTo : "Showing everything"}
          </span>
          <button
            type="button"
            onClick={() => {
              onSearch(
                mine
                  ? { ...without(search, "page"), all: true }
                  : without(search, "all", "page"),
              );
            }}
            className="text-accent underline"
          >
            {mine ? "Show everything" : "Show my interests"}
          </button>
        </p>
      )}
      {(search.j ?? search.t ?? search.days) && (
        <ul
          aria-label="Active filters"
          className="mt-2 flex flex-wrap gap-2 text-sm"
        >
          {search.j && (
            <FilterChip
              label={`Jurisdictions: ${search.j.split(",").map(jurisdictionName).join(", ")}`}
              onRemove={() => {
                onSearch(without(search, "j", "page"));
              }}
            />
          )}
          {search.t && (
            <FilterChip
              label={`Topic filter: ${search.t.replace(":", ": ")}`}
              onRemove={() => {
                onSearch(without(search, "t", "page"));
              }}
            />
          )}
          {search.days && (
            <FilterChip
              label={`Changed in the last ${String(search.days)} days`}
              onRemove={() => {
                onSearch(without(search, "days", "page"));
              }}
            />
          )}
        </ul>
      )}
      {result.isError && (
        <p role="alert" className="mt-3 text-critical">
          {problemText(result.error, "The items could not be loaded.")}
        </p>
      )}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <caption
            className="mb-2 text-left text-sm text-text-muted"
            aria-live="polite"
          >
            {caption}
          </caption>
          <thead>
            <tr className="border-b border-border">
              <th
                scope="col"
                aria-sort={ariaSort("title")}
                className="py-2 pr-4"
              >
                Title
              </th>
              <th scope="col" className="py-2 pr-4">
                Jurisdictions
              </th>
              <th scope="col" className="py-2 pr-4">
                Source
              </th>
              <th
                scope="col"
                aria-sort={ariaSort("published")}
                className="py-2 pr-4"
              >
                Published
              </th>
              <th
                scope="col"
                aria-sort={ariaSort("changed")}
                className="py-2 pr-4"
              >
                Last changed
              </th>
              <th scope="col" className="py-2">
                Severity
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-b border-border align-top">
                <td className="py-2 pr-4">
                  <Title item={item} />
                </td>
                <td className="py-2 pr-4">
                  {item.jurisdictions
                    .map((j) => j.code)
                    .filter(Boolean)
                    .join(", ")}
                </td>
                <td className="py-2 pr-4">{item.source_name ?? ""}</td>
                <td className="py-2 pr-4">{date(item.published_at)}</td>
                <td className="py-2 pr-4">{date(item.last_changed_at)}</td>
                <td className="py-2">{item.severity ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav aria-label="Pages" className="mt-3 flex items-center gap-3">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => {
            onSearch({ ...search, page: page - 1 });
          }}
          className="rounded border border-border px-2 py-1 disabled:opacity-50"
        >
          Previous page
        </button>
        <span>
          Page {String(page)} of {String(pages)}
        </span>
        <button
          type="button"
          disabled={page >= pages}
          onClick={() => {
            onSearch({ ...search, page: page + 1 });
          }}
          className="rounded border border-border px-2 py-1 disabled:opacity-50"
        >
          Next page
        </button>
      </nav>
    </>
  );
}
