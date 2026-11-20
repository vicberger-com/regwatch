/**
 * Dates and times in the user's time zone (M9 preference, use testing U-M9-1). The shell sets
 * the zone from the signed-in user's preferences; until then, and for a zone the browser does
 * not know, the browser's own zone is used.
 */
let zone: string | undefined;

export function setTimeZone(value: string | undefined): void {
  if (!value) {
    zone = undefined;
    return;
  }
  try {
    new Intl.DateTimeFormat("en", { timeZone: value }); // throws for an unknown zone
    zone = value;
  } catch {
    zone = undefined;
  }
}

function format(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions,
): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    ...options,
    ...(zone ? { timeZone: zone } : {}),
  });
}

export const formatDate = (value: string | number | Date) =>
  format(value, { dateStyle: "medium" });
export const formatDateTime = (value: string | number | Date) =>
  format(value, { dateStyle: "medium", timeStyle: "short" });
export const formatTime = (value: string | number | Date) =>
  format(value, { timeStyle: "short" });
