import { useState } from "react";

import type { ActivityRow } from "./scale";

type Column = "name" | "count" | "last" | "severity";
const SEVERITY_ORDER: Record<string, number> = {
  none: 0,
  info: 1,
  notable: 2,
  major: 3,
};

/**
 * The map's data as a table (screens.md, REQ-18): one row per jurisdiction or region with
 * changes, sortable by any column with the sort stated in `aria-sort` and in the caption.
 */
export function ActivityTable(props: {
  rows: readonly ActivityRow[];
  nameOf: (code: string) => string;
  caption: string;
  onSelect: (code: string) => void;
}) {
  const [sort, setSort] = useState<{ by: Column; up: boolean }>({
    by: "last",
    up: false,
  });
  const value = (r: ActivityRow, by: Column): string | number =>
    by === "name"
      ? props.nameOf(r.code)
      : by === "count"
        ? r.count
        : by === "severity"
          ? (SEVERITY_ORDER[r.max_severity] ?? 0)
          : (r.last_changed_at ?? "");
  const rows = props.rows
    .filter((r) => r.count > 0)
    .sort((a, b) => {
      const x = value(a, sort.by);
      const y = value(b, sort.by);
      const order =
        typeof x === "number" && typeof y === "number"
          ? x - y
          : String(x).localeCompare(String(y));
      return sort.up ? order : -order;
    });
  const header = (by: Column, label: string) => {
    const active = sort.by === by;
    return (
      <th
        scope="col"
        aria-sort={active ? (sort.up ? "ascending" : "descending") : undefined}
        className="py-2 pr-4"
      >
        <button
          type="button"
          onClick={() => {
            setSort({ by, up: active ? !sort.up : by === "name" });
          }}
          className="font-semibold underline-offset-2 hover:underline"
        >
          {label}
          <span aria-hidden="true">
            {active ? (sort.up ? " ▲" : " ▼") : ""}
          </span>
        </button>
      </th>
    );
  };
  return (
    <table className="w-full border-collapse text-left">
      <caption className="mb-2 text-left text-sm text-text-muted">
        {props.caption}
      </caption>
      <thead>
        <tr className="border-b border-border">
          {header("name", "Jurisdiction")}
          {header("count", "Items changed")}
          {header("last", "Last change")}
          {header("severity", "Highest severity")}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.code} className="border-b border-border">
            <th scope="row" className="py-2 pr-4 font-normal">
              <button
                type="button"
                className="text-accent underline"
                onClick={() => {
                  props.onSelect(r.code);
                }}
              >
                {props.nameOf(r.code)}
              </button>
            </th>
            <td className="py-2 pr-4">{String(r.count)}</td>
            <td className="py-2 pr-4">
              {r.last_changed_at
                ? new Date(r.last_changed_at).toLocaleDateString()
                : "—"}
            </td>
            <td className="py-2">{r.max_severity}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
