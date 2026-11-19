import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { problemText } from "@/lib/auth/session";

import { activityQuery, PERIODS } from "./api";
import { JurisdictionList } from "./JurisdictionList";
import { legend, steps as stepsOf, type Encoding } from "./scale";
import { WorldMap } from "./WorldMap";

const names = new Intl.DisplayNames(["en"], {
  type: "region",
  fallback: "code",
});
const SUPRANATIONAL: Record<string, string> = {
  EU: "European Union",
  COE: "Council of Europe",
  OECD: "OECD",
  UN: "United Nations",
  INTL: "International",
};
export function jurisdictionName(code: string): string {
  if (SUPRANATIONAL[code]) return SUPRANATIONAL[code];
  try {
    return /^[A-Z]{2}$/.test(code) ? (names.of(code) ?? code) : code;
  } catch {
    return code;
  }
}

const ENCODINGS: { value: Encoding; label: string }[] = [
  { value: "recency", label: "Recency" },
  { value: "count", label: "Number of changes" },
  { value: "severity", label: "Highest severity" },
];

const plural = (n: number, one: string, many: string) =>
  `${String(n)} ${n === 1 ? one : many}`;

/** `/`: the world map of change activity with its accessible list (M6 acceptance 1, 5). */
export function MapPage() {
  const [period, setPeriod] = useState<number>(30);
  const [encoding, setEncoding] = useState<Encoding>("recency");
  const [selected, setSelected] = useState<string | null>(null);
  const activity = useQuery(activityQuery(period));
  const rows = useMemo(() => activity.data?.rows ?? [], [activity.data]);

  const steps = useMemo(() => {
    if (!activity.data) return new Map();
    const range = {
      start: new Date(activity.data.period_start),
      end: new Date(activity.data.period_end),
    };
    return stepsOf(rows, encoding, range);
  }, [activity.data, rows, encoding]);
  const byCode = useMemo(() => new Map(rows.map((r) => [r.code, r])), [rows]);
  const describe = (code: string) => {
    const row = byCode.get(code);
    if (!row || row.count === 0) return "No changes in this period";
    const last = row.last_changed_at
      ? `, last ${new Date(row.last_changed_at).toLocaleDateString()}`
      : "";
    return `${plural(row.count, "item", "items")} changed${last}; highest severity ${row.max_severity}`;
  };
  const entries = useMemo(
    () =>
      rows
        .filter((r) => r.count > 0)
        .sort((a, b) =>
          (b.last_changed_at ?? "").localeCompare(a.last_changed_at ?? ""),
        )
        .map((r) => ({
          code: r.code,
          name: jurisdictionName(r.code),
          summary: describe(r.code),
        })),
    // describe reads byCode, which follows rows
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, byCode],
  );
  const periodText = `the last ${String(period)} days`;
  const labels = legend(encoding);

  return (
    <>
      <h1 className="text-2xl font-semibold">Map</h1>
      <div
        className="mt-4 flex flex-wrap items-end gap-4"
        role="toolbar"
        aria-label="Map options"
      >
        <label className="flex flex-col text-sm">
          Period
          <select
            className="mt-1 rounded border border-border bg-surface px-2 py-1"
            value={period}
            onChange={(e) => {
              setPeriod(Number(e.target.value));
            }}
          >
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                Last {String(p)} days
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Colour by
          <select
            className="mt-1 rounded border border-border bg-surface px-2 py-1"
            value={encoding}
            onChange={(e) => {
              setEncoding(e.target.value as Encoding);
            }}
          >
            {ENCODINGS.map((e) => (
              <option key={e.value} value={e.value}>
                {e.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p role="status" className="mt-3 text-sm text-text-muted">
        {activity.isPending
          ? "Loading activity…"
          : activity.isError
            ? ""
            : `${plural(entries.length, "jurisdiction", "jurisdictions")} with changes in ${periodText}`}
      </p>
      {activity.isError && (
        <p role="alert" className="mt-2 text-critical">
          {problemText(activity.error, "The activity could not be loaded.")}
        </p>
      )}
      <div className="mt-3 grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div>
          <WorldMap
            label={`Map of change activity in ${periodText}, coloured by ${encoding}; the list of jurisdictions has the same information`}
            steps={steps}
            selected={selected}
            onSelect={setSelected}
            describe={describe}
          />
          <ol aria-label="Legend" className="mt-2 flex flex-wrap gap-3 text-sm">
            {labels.map((text, i) => (
              <li key={i} className="flex items-center gap-1">
                <span
                  aria-hidden="true"
                  className="inline-block h-3 w-6 rounded-sm border border-border"
                  style={{ background: `var(--map-${String(i)})` }}
                />
                {text || <span className="sr-only">step {String(i)}</span>}
              </li>
            ))}
          </ol>
        </div>
        <JurisdictionList
          label={`Jurisdictions with changes in ${periodText}, newest first`}
          entries={entries}
          selected={selected}
          onSelect={setSelected}
        />
      </div>
    </>
  );
}
