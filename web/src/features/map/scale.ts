/**
 * The map's five colour steps (screens.md map scale, tokens `--map-0` to `--map-4`): step 0 is
 * "no change in the period", steps 1 to 4 rise with the chosen encoding.
 */
export type Encoding = "recency" | "count" | "severity";
export type Step = 0 | 1 | 2 | 3 | 4;

export interface ActivityRow {
  code: string;
  count: number;
  last_changed_at?: string | null;
  max_severity: "none" | "info" | "notable" | "major";
}

const SEVERITY: Record<ActivityRow["max_severity"], Step> = {
  none: 0,
  info: 2,
  notable: 3,
  major: 4,
};

function clamp(step: number): Step {
  return Math.min(4, Math.max(1, Math.ceil(step))) as Step;
}

/** The step of one row: recency by quarter of the period, count on a log scale. */
export function step(
  row: ActivityRow | undefined,
  encoding: Encoding,
  period: { start: Date; end: Date },
  maxCount: number,
): Step {
  if (!row || row.count <= 0) return 0;
  if (encoding === "severity") return SEVERITY[row.max_severity];
  if (encoding === "count") {
    return maxCount <= 1
      ? 4
      : clamp((4 * Math.log1p(row.count)) / Math.log1p(maxCount));
  }
  const last = row.last_changed_at
    ? Date.parse(row.last_changed_at)
    : Number.NaN;
  const span = period.end.getTime() - period.start.getTime();
  if (Number.isNaN(last) || span <= 0) return 1;
  const age = Math.min(1, Math.max(0, (period.end.getTime() - last) / span));
  return clamp(4 - Math.floor(age * 4)); // newest quarter 4, oldest quarter 1
}

export function steps(
  rows: readonly ActivityRow[],
  encoding: Encoding,
  period: { start: Date; end: Date },
): Map<string, Step> {
  const maxCount = Math.max(0, ...rows.map((r) => r.count));
  return new Map(
    rows.map((r) => [r.code, step(r, encoding, period, maxCount)]),
  );
}

/** Legend labels, lowest step first. */
export function legend(encoding: Encoding): string[] {
  if (encoding === "severity")
    return ["No change", "", "Info", "Notable", "Major"];
  if (encoding === "count")
    return ["No change", "Fewest", "", "", "Most changes"];
  return ["No change", "Oldest in period", "", "", "Most recent"];
}
