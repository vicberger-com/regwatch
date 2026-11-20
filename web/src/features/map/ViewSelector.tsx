import type { Facet, Term } from "@/features/taxonomy/api";

import type { MapView } from "./api";

/** The terms of a facet's tree, depth first, active only, with an indented label. */
export function flatTerms(
  terms: readonly Term[] | undefined,
  depth = 0,
): { key: string; label: string }[] {
  const list: readonly Term[] = Array.isArray(terms) ? terms : [];
  return list
    .filter(
      (t) =>
        t.active && typeof t.key === "string" && typeof t.label === "string",
    )
    .flatMap((t) => [
      { key: t.key, label: `${"  ".repeat(depth)}${t.label}` },
      ...flatTerms(t.children, depth + 1),
    ]);
}

/**
 * The view selector (screens.md): country, region, or one term of a facet flagged for the view
 * selector in M2. Facets and regions come from the taxonomy (`taxonomy.read`); without it only
 * the country view is offered.
 */
export function ViewSelector(props: {
  view: MapView;
  onChange: (view: MapView) => void;
  facets: readonly Facet[];
  regionsAvailable: boolean;
}) {
  const { view, onChange } = props;
  const given: readonly Facet[] = Array.isArray(props.facets)
    ? props.facets
    : [];
  const facets = given.filter(
    (f) =>
      f.show_in_view_selector &&
      typeof f.key === "string" &&
      typeof f.label === "string",
  );
  const facet = facets.find((f) => f.key === view.facet);
  const value = view.facet ? `facet:${view.facet}` : view.by;
  return (
    <>
      <label className="flex flex-col text-sm">
        View
        <select
          className="mt-1 rounded border border-border bg-surface px-2 py-1"
          value={value}
          onChange={(e) => {
            const chosen = e.target.value;
            if (chosen === "region") onChange({ by: "region" });
            else if (chosen.startsWith("facet:"))
              onChange({ by: "country", facet: chosen.slice(6) });
            else onChange({ by: "country" });
          }}
        >
          <option value="country">Country</option>
          {props.regionsAvailable && <option value="region">Region</option>}
          {facets.map((f) => (
            <option key={f.key} value={`facet:${f.key}`}>
              {f.label}
            </option>
          ))}
        </select>
      </label>
      {facet && (
        <label className="flex flex-col text-sm">
          {facet.label}
          <select
            className="mt-1 rounded border border-border bg-surface px-2 py-1"
            value={view.term ?? ""}
            onChange={(e) => {
              const rest: MapView = {
                by: view.by,
                ...(view.facet ? { facet: view.facet } : {}),
              };
              onChange(
                e.target.value ? { ...rest, term: e.target.value } : rest,
              );
            }}
          >
            <option value="">Choose a value</option>
            {flatTerms(facet.terms).map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
      )}
    </>
  );
}
