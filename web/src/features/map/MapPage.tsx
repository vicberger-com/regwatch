import { useQuery } from "@tanstack/react-query";
import { useRouteContext } from "@tanstack/react-router";
import { useCallback, useMemo, useState } from "react";

import { regionsQuery } from "@/features/jurisdictions/api";
import { preferencesQuery, viewsQuery } from "@/features/me/api";
import { facetsQuery } from "@/features/taxonomy/api";
import { hasPermission, problemText } from "@/lib/auth/session";

import { activityQuery, PERIODS, type MapView } from "./api";
import { jurisdictionName } from "./names";
import { ActivityTable } from "./ActivityTable";
import { JurisdictionList } from "./JurisdictionList";
import { JurisdictionPanel } from "./JurisdictionPanel";
import {
  legend,
  steps as stepsOf,
  wellFormed,
  type ActivityRow,
  type Encoding,
  type Step,
} from "./scale";
import { ViewSelector } from "./ViewSelector";
import { WorldMap } from "./WorldMap";

const ENCODINGS: { value: Encoding; label: string }[] = [
  { value: "recency", label: "Recency" },
  { value: "count", label: "Number of changes" },
  { value: "severity", label: "Highest severity" },
];

const plural = (n: number, one: string, many: string) =>
  `${String(n)} ${n === 1 ? one : many}`;

/** The regions of an answer that have the documented shape, with two-letter members only. */
export function validRegions(
  data: unknown,
): { code: string; name: string; members: string[] }[] {
  if (!Array.isArray(data)) return [];
  const out: { code: string; name: string; members: string[] }[] = [];
  for (const item of data as unknown[]) {
    if (typeof item !== "object" || item === null) continue;
    const r = item as Record<string, unknown>;
    if (typeof r.code !== "string" || !Array.isArray(r.jurisdiction_codes))
      continue;
    const members = (r.jurisdiction_codes as unknown[]).filter(
      (c): c is string => typeof c === "string" && /^[A-Z]{2}$/.test(c),
    );
    out.push({
      code: r.code,
      name: typeof r.name === "string" ? r.name : r.code,
      members,
    });
  }
  return out;
}

/**
 * The saved view chosen as the landing view: undefined while unknown, null when there is none
 * (or it is no longer one the user can see), else the view.
 */
function useLandingView() {
  const prefs = useQuery(preferencesQuery);
  const id = prefs.data?.landing_view_id ?? null;
  const views = useQuery({ ...viewsQuery, enabled: id !== null });
  if (prefs.isPending) return undefined;
  if (!prefs.isSuccess || id === null) return null;
  if (views.isPending) return undefined;
  const list = Array.isArray(views.data) ? views.data : [];
  return list.find((v) => v.id === id) ?? null;
}

/** `/`: the world map of change activity with its accessible list (M6 acceptance 1, 5). */
export function MapPage() {
  const [period, setPeriod] = useState<number>(30);
  const [encoding, setEncoding] = useState<Encoding>("recency");
  const [asTable, setAsTable] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setViewState] = useState<MapView>({ by: "country" });
  // The user's landing view (M9 Defaults), applied once when it is known. A view that is
  // gone or no longer visible to the user is simply not in their list: the map stays as is.
  const landing = useLandingView();
  const [applied, setApplied] = useState(false);
  if (!applied && landing !== undefined) {
    setApplied(true);
    if (landing) {
      setPeriod(
        (PERIODS as readonly number[]).includes(landing.period_days)
          ? landing.period_days
          : 30,
      );
      if (
        landing.color_scheme === "count" ||
        landing.color_scheme === "severity"
      )
        setEncoding(landing.color_scheme);
      const [facet, terms] =
        Object.entries(landing.filters.terms ?? {})[0] ?? [];
      const term = Array.isArray(terms) ? terms[0] : undefined;
      setViewState({
        by: landing.view_by === "region" ? "region" : "country",
        ...(typeof facet === "string" && typeof term === "string"
          ? { facet, term }
          : {}),
      });
    }
  }
  const { me } = useRouteContext({ from: "/authed" });
  const taxonomy = hasPermission(me, "taxonomy.read");
  const facets = useQuery({ ...facetsQuery, enabled: taxonomy });
  const regions = useQuery({ ...regionsQuery, enabled: taxonomy });
  const setView = (next: MapView) => {
    setViewState(next);
    setSelected(null); // a code of one view means nothing in another
  };
  // Until a facet's value is chosen, the view shows every change (acceptance 2).
  const asked: MapView = view.facet && !view.term ? { by: view.by } : view;
  const activity = useQuery(activityQuery(period, asked));
  // A region's member countries, and each country's region, for the region view.
  // Only well-formed regions: a broken answer must not take the map down.
  const regionList = useMemo(() => validRegions(regions.data), [regions.data]);
  const members = useMemo(
    () => new Map(regionList.map((r) => [r.code, r.members])),
    [regionList],
  );
  const regionOf = useMemo(() => {
    const out = new Map<string, string>();
    for (const [region, codes] of members)
      for (const c of codes) out.set(c, region);
    return out;
  }, [members]);
  const regionNames = useMemo(
    () => new Map(regionList.map((r) => [r.code, r.name])),
    [regionList],
  );
  const nameOf = useCallback(
    (code: string) =>
      view.by === "region"
        ? (regionNames.get(code) ?? code)
        : jurisdictionName(code),
    [view.by, regionNames],
  );
  // Only well-formed rows: a broken answer must not take the page down.
  const rows = useMemo(() => wellFormed(activity.data?.rows), [activity.data]);

  const steps = useMemo(() => {
    if (!activity.data) return new Map();
    const range = {
      start: new Date(activity.data.period_start),
      end: new Date(activity.data.period_end),
    };
    const own = stepsOf(rows, encoding, range);
    if (view.by !== "region") return own;
    // The region view shades every member country with its region's step.
    const out = new Map<string, Step>();
    for (const [region, step] of own)
      for (const c of members.get(region) ?? []) out.set(c, step);
    return out;
  }, [activity.data, rows, encoding, view.by, members]);
  const byCode = useMemo(() => new Map(rows.map((r) => [r.code, r])), [rows]);
  const closePanel = useCallback(() => {
    setSelected(null);
  }, []);
  /** A row by its own code (a region in the region view), for the list and the status. */
  const describeOwn = (code: string) => describeRow(byCode.get(code));
  const describe = (code: string) => {
    return describeRow(
      byCode.get(view.by === "region" ? (regionOf.get(code) ?? code) : code),
    );
  };
  function describeRow(row: ActivityRow | undefined) {
    if (!row || row.count === 0) return "No changes in this period";
    const last = row.last_changed_at
      ? `, last ${new Date(row.last_changed_at).toLocaleDateString()}`
      : "";
    return `${plural(row.count, "item", "items")} changed${last}; highest severity ${row.max_severity}`;
  }
  const entries = useMemo(
    () =>
      rows
        .filter((r) => r.count > 0)
        .sort((a, b) =>
          (b.last_changed_at ?? "").localeCompare(a.last_changed_at ?? ""),
        )
        .map((r) => ({
          code: r.code,
          name: nameOf(r.code),
          summary: describeOwn(r.code),
        })),
    // describe reads byCode, which follows rows
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, byCode, nameOf],
  );
  const periodText = `the last ${String(period)} days`;
  const labels = legend(encoding);

  return (
    <>
      <h1 className="text-2xl font-semibold">Map</h1>
      <div
        className="mt-4 flex flex-wrap items-end gap-4"
        role="group"
        aria-label="Map options"
      >
        <fieldset className="flex flex-col text-sm">
          <legend>Show as</legend>
          <div className="mt-1 flex gap-3">
            {(["Map", "Table"] as const).map((label) => (
              <label key={label} className="flex items-center gap-1">
                <input
                  type="radio"
                  name="show-as"
                  checked={asTable === (label === "Table")}
                  onChange={() => {
                    setAsTable(label === "Table");
                  }}
                />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
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
        <ViewSelector
          view={view}
          onChange={setView}
          facets={facets.data ?? []}
          regionsAvailable={regions.isSuccess}
        />
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
            : `${plural(entries.length, "jurisdiction", "jurisdictions")} with changes in ${periodText}${
                selected
                  ? `. Selected: ${nameOf(selected)}, ${describeOwn(selected)}`
                  : ""
              }`}
      </p>
      {activity.isError && (
        <p role="alert" className="mt-2 text-critical">
          {problemText(activity.error, "The activity could not be loaded.")}
        </p>
      )}
      <div className="mt-3 grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div>
          {asTable ? (
            <ActivityTable
              rows={rows}
              nameOf={nameOf}
              placeLabel={view.by === "region" ? "Region" : "Jurisdiction"}
              caption={`${plural(entries.length, view.by === "region" ? "region" : "jurisdiction", view.by === "region" ? "regions" : "jurisdictions")} with changes in ${periodText}`}
              onSelect={setSelected}
            />
          ) : (
            <>
              <WorldMap
                label={`Map of change activity in ${periodText}, coloured by ${encoding}; the list of jurisdictions has the same information`}
                steps={steps}
                selected={view.by === "region" ? null : selected}
                onSelect={(code) => {
                  setSelected(
                    view.by === "region" ? (regionOf.get(code) ?? null) : code,
                  );
                }}
                describe={describe}
              />
              <ol
                aria-label="Legend"
                className="mt-2 flex flex-wrap gap-3 text-sm"
              >
                {labels.map((text, i) => (
                  <li key={i} className="flex items-center gap-1">
                    <span
                      aria-hidden="true"
                      className="inline-block h-3 w-6 rounded-sm border border-border"
                      style={{
                        backgroundColor: `var(--map-${String(i)})`,
                        backgroundImage: `var(--map-pattern-${String(i)})`,
                      }}
                    />
                    {text || <span className="sr-only">step {String(i)}</span>}
                  </li>
                ))}
              </ol>
              <p className="mt-1 text-sm text-text-muted">
                Boundaries from Natural Earth; disputed areas are drawn neutral.
                The map implies no endorsement of any boundary or claim.
              </p>
            </>
          )}
        </div>
        <div className="flex flex-col gap-4">
          {selected && (
            <JurisdictionPanel
              code={selected}
              name={nameOf(selected)}
              scope={{
                // A body without a region (EU, COE) has its own row in the region view.
                ...(view.by === "region" && members.has(selected)
                  ? { regions: [selected] }
                  : { jurisdictions: [selected] }),
                ...(asked.facet && asked.term
                  ? { terms: { [asked.facet]: [asked.term] } }
                  : {}),
              }}
              link={
                view.by === "region"
                  ? null
                  : {
                      j: selected,
                      days: period,
                      ...(asked.facet && asked.term
                        ? { t: `${asked.facet}:${asked.term}` }
                        : {}),
                    }
              }
              row={byCode.get(selected)}
              periodDays={period}
              periodStart={activity.data?.period_start}
              onClose={closePanel}
            />
          )}
          <JurisdictionList
            label={`${view.by === "region" ? "Regions" : "Jurisdictions"} with changes in ${periodText}, newest first`}
            entries={entries}
            selected={selected}
            onSelect={setSelected}
          />
        </div>
      </div>
    </>
  );
}
