/**
 * Appearance from the user's preferences (M9): theme, font scale, density, motion, toolbar
 * labels and hit targets, applied to <html> at once. A copy is kept in localStorage and
 * applied in main.tsx before the first render, so a reload never flashes the wrong theme
 * (M9 acceptance 1; no inline script, which the CSP forbids).
 */
import type { Schemas } from "@/lib/api/client";

import { isTheme, type Theme } from "./theme";

export type Preferences = Schemas["Preferences"];
export const APPEARANCE_KEY = "regwatch.appearance";

export interface Appearance {
  theme: Theme;
  fontScale: number;
  density: number;
  motion: "system" | "reduce" | "full";
  labels: "hover" | "always";
  largeTargets: boolean;
}

const DENSITY: Record<string, number> = {
  compact: 0.85,
  default: 1,
  comfortable: 1.2,
};
const SCALES = new Set([100, 112, 125, 150, 175, 200]);

/** The effective appearance: the accessibility preset fills in what the user left at default. */
export function resolve(
  prefs: Partial<Preferences> | undefined,
  darkSystem: boolean,
): Appearance {
  const p = prefs ?? {};
  const preset = p.accessibility_preset === true;
  const chosen = p.theme && p.theme !== "system" ? p.theme : undefined;
  const theme: Theme = isTheme(chosen)
    ? chosen
    : preset
      ? "high-contrast"
      : darkSystem
        ? "dark"
        : "light";
  const scale = SCALES.has(p.font_scale ?? 100) ? (p.font_scale ?? 100) : 100;
  const motion =
    p.reduced_motion === "on" ||
    (preset && (p.reduced_motion ?? "system") === "system")
      ? "reduce"
      : p.reduced_motion === "off"
        ? "full"
        : "system";
  return {
    theme,
    fontScale: (preset && scale === 100 ? 125 : scale) / 100,
    density: DENSITY[p.density ?? "default"] ?? 1,
    motion,
    labels: p.toolbar_labels === "always" || preset ? "always" : "hover",
    largeTargets: preset,
  };
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function applyAppearance(
  a: Appearance,
  root: HTMLElement = document.documentElement,
): void {
  root.dataset.theme = a.theme;
  root.style.setProperty("--font-scale", String(a.fontScale));
  root.style.setProperty("--density", String(a.density));
  if (a.motion === "system") delete root.dataset.motion;
  else root.dataset.motion = a.motion;
  root.dataset.labels = a.labels;
  if (a.largeTargets) root.dataset.hit = "large";
  else delete root.dataset.hit;
  try {
    storage()?.setItem(APPEARANCE_KEY, JSON.stringify(a));
    storage()?.setItem("regwatch.theme", a.theme); // the shell's theme switch reads this
  } catch {
    // applied for this page view only
  }
}

/** The stored copy, checked field by field (it is only a cache of the server's preferences). */
export function readStoredAppearance(): Appearance | null {
  try {
    const raw = storage()?.getItem(APPEARANCE_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<Appearance>;
    if (
      !isTheme(v.theme) ||
      typeof v.fontScale !== "number" ||
      typeof v.density !== "number"
    )
      return null;
    return {
      theme: v.theme,
      fontScale: Math.min(2, Math.max(1, v.fontScale)),
      density: Math.min(1.2, Math.max(0.85, v.density)),
      motion:
        v.motion === "reduce" || v.motion === "full" ? v.motion : "system",
      labels: v.labels === "always" ? "always" : "hover",
      largeTargets: v.largeTargets === true,
    };
  } catch {
    return null;
  }
}

export function systemIsDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}
