/**
 * The values a stock report asks for (CP-31 `ReportParameterDef`): a jurisdiction, the days
 * covered, the topics. Used wherever a stock report is previewed or produced (use testing
 * U-M7-1: without them, a report with a required parameter could not be made from any screen).
 * The server checks every value again (`reports/templates.py apply`).
 */
import { useQuery } from "@tanstack/react-query";
import { useId } from "react";

import { interestOptionsQuery } from "@/features/me/InterestsEditor";
import type { Schemas } from "@/lib/api/client";

export type ParamDef = Schemas["ReportParameterDef"];
export type Params = Record<string, unknown>;
const PERIODS = [7, 30, 90, 365];
const field = "rounded border border-border bg-surface px-2 py-1";

/** The definitions' defaults, as the server would use them. */
export function defaults(defs: readonly ParamDef[] | undefined): Params {
  const out: Params = {};
  for (const d of defs ?? [])
    if (d.key && d.default !== undefined && d.default !== null)
      out[d.key] = d.default;
  return out;
}

/** The required parameters still without a value; empty when the report can be made. */
export function missing(defs: readonly ParamDef[] | undefined, values: Params) {
  return (defs ?? []).filter(
    (d) => d.required && d.key && values[d.key] === undefined,
  );
}

export function ParamFields(props: {
  defs: readonly ParamDef[] | undefined;
  values: Params;
  onChange: (values: Params) => void;
}) {
  const id = useId();
  const defs = (props.defs ?? []).filter((d) => d.key);
  const options = useQuery({
    ...interestOptionsQuery,
    enabled: defs.length > 0,
  });
  if (defs.length === 0) return null;
  const set = (key: string, value: unknown) => {
    props.onChange(
      Object.fromEntries([
        ...Object.entries(props.values).filter(([k]) => k !== key),
        ...(value === undefined ? [] : [[key, value] as const]),
      ]),
    );
  };
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="font-semibold">Report settings</legend>
      {defs.map((d) => {
        const key = d.key ?? "";
        const label = `${d.label ?? key}${d.required ? "" : " (optional)"}`;
        const fid = `${id}-${key}`;
        if (d.type === "jurisdiction")
          return (
            <label key={key} htmlFor={fid} className="flex flex-col gap-1">
              {label}
              <select
                id={fid}
                className={field}
                required={d.required}
                value={(() => {
                  const v = props.values[key];
                  return typeof v === "string" ? v : "";
                })()}
                onChange={(e) => {
                  set(key, e.target.value || undefined);
                }}
              >
                <option value="">Choose a jurisdiction</option>
                {options.data?.jurisdictions.map((j) => (
                  <option key={j.code} value={j.code}>
                    {j.name}
                  </option>
                ))}
              </select>
            </label>
          );
        if (d.type === "period_days")
          return (
            <label key={key} htmlFor={fid} className="flex flex-col gap-1">
              {label}
              <select
                id={fid}
                className={field}
                value={(() => {
                  const v = props.values[key];
                  return String(typeof v === "number" ? v : (d.default ?? 30));
                })()}
                onChange={(e) => {
                  set(key, Number(e.target.value));
                }}
              >
                {[...new Set([...PERIODS, d.default ?? 30])]
                  .sort((a, b) => a - b)
                  .map((n) => (
                    <option key={n} value={n}>
                      Last {n} days
                    </option>
                  ))}
              </select>
            </label>
          );
        if (d.type === "facet_terms") {
          const chosen = props.values[key] as
            Record<string, string[]> | undefined;
          const current = chosen
            ? Object.entries(chosen).flatMap(([f, ts]) =>
                ts.map((t) => `${f}:${t}`),
              )[0]
            : "";
          return (
            <label key={key} htmlFor={fid} className="flex flex-col gap-1">
              {label}
              <select
                id={fid}
                className={field}
                required={d.required}
                value={current ?? ""}
                onChange={(e) => {
                  const [facet, term] = e.target.value.split(":", 2);
                  set(key, facet && term ? { [facet]: [term] } : undefined);
                }}
              >
                <option value="">Choose a topic</option>
                {options.data?.facets.map((f) => (
                  <optgroup key={f.key} label={f.label}>
                    {f.terms.map((t) => (
                      <option key={t.key} value={`${f.key}:${t.key}`}>
                        {t.label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
          );
        }
        return null; // date_range and saved_view: no stock report asks for them yet
      })}
    </fieldset>
  );
}
