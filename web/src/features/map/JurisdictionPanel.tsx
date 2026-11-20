import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useEffect, useRef } from "react";

import {
  searchQuery,
  type ItemSummary,
  type Query,
} from "@/features/items/api";
import type { ItemsSearch } from "@/features/items/ItemsPage";
import { problemText } from "@/lib/auth/session";

import type { ActivityRow } from "./scale";
import { formatDate } from "@/lib/time/format";

const LEVELS = ["major", "notable", "info"] as const;

/**
 * The right panel for a selected jurisdiction (screens.md `/`): counts by severity, the latest
 * ten items changed in the period, and a link to the items table filtered the same way. Focus
 * moves into it when it opens and back to where it came from when it closes.
 */
export function JurisdictionPanel(props: {
  code: string;
  name: string;
  /** The filters that select this place's items (a jurisdiction, or a region) and the view's. */
  scope: NonNullable<Query["filters"]>;
  /** Where "All items" leads; none when the items table cannot express the view. */
  link: ItemsSearch | null;
  row: (ActivityRow & { breakdown?: Record<string, number> }) | undefined;
  periodDays: number;
  periodStart: string | undefined;
  onClose: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<Element | null>(null);
  const panel = useRef<HTMLElement>(null);
  const { onClose } = props;
  // Escape closes the panel while focus is inside it (screens.md: closable, focus returns).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && panel.current?.contains(document.activeElement))
        onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);
  useEffect(() => {
    opener.current = document.activeElement;
    heading.current?.focus();
    return () => {
      if (opener.current instanceof HTMLElement && opener.current.isConnected)
        opener.current.focus();
    };
  }, [props.code]);
  const latest = useQuery({
    ...searchQuery({
      filters: {
        ...props.scope,
        ...(props.periodStart ? { changed: { from: props.periodStart } } : {}),
      },
      sort: "last_changed_desc",
      page: 1,
      page_size: 10,
      highlight: false,
      facet_counts: false,
    }),
  });
  const items = (latest.data?.items ?? []) as ItemSummary[];
  const { name } = props;
  const id = `panel-${props.code}`;
  return (
    <aside
      ref={panel}
      aria-labelledby={id}
      className="rounded border border-border bg-surface p-4"
    >
      <div className="flex items-start justify-between gap-2">
        <h2
          id={id}
          ref={heading}
          tabIndex={-1}
          className="text-lg font-semibold"
        >
          {name}
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 hover:bg-bg"
        >
          <X aria-hidden="true" className="h-4 w-4" />
          <span className="sr-only">
            Close the {name} panel (Escape returns to the list)
          </span>
        </button>
      </div>
      <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 text-sm">
        <dt className="text-text-muted">Items changed</dt>
        <dd>{String(props.row?.count ?? 0)}</dd>
        {LEVELS.map((level) => (
          <div key={level} className="contents">
            <dt className="capitalize text-text-muted">{level}</dt>
            <dd>{String(props.row?.breakdown?.[level] ?? 0)}</dd>
          </div>
        ))}
      </dl>
      <h3 className="mt-4 font-semibold">Latest changes</h3>
      {latest.isPending ? (
        <p role="status" className="text-sm">
          Loading…
        </p>
      ) : latest.isError ? (
        <p role="alert" className="text-sm text-critical">
          {problemText(latest.error, "The items could not be loaded.")}
        </p>
      ) : items.length === 0 ? (
        <p className="text-sm text-text-muted">
          No items changed in this period.
        </p>
      ) : (
        <ol className="mt-1 space-y-1 text-sm">
          {items.map((item) => (
            <li key={item.id}>
              <Link
                to="/items/$id"
                params={{ id: item.id }}
                className="text-accent underline-offset-2 hover:underline"
              >
                <bdi>{item.title}</bdi>
              </Link>
              <span className="block text-text-muted">
                {item.last_changed_at ? formatDate(item.last_changed_at) : "—"}
                {item.severity ? ` · ${item.severity}` : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
      {props.link && (
        <Link
          to="/items"
          search={props.link}
          className="mt-3 inline-block text-accent underline"
        >
          All items for {name}
          {props.link.t ? ` (${props.link.t.replace(":", ": ")})` : ""} in the
          last {String(props.periodDays)} days
        </Link>
      )}
    </aside>
  );
}
