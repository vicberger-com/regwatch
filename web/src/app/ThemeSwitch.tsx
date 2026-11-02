import { useState } from "react";

import {
  applyTheme,
  nextTheme,
  readStoredTheme,
  THEME_LABELS,
  type Theme,
} from "./theme";

export function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme());
  const upcoming = nextTheme(theme);

  function cycle() {
    applyTheme(upcoming);
    setTheme(upcoming);
  }

  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={`Theme: ${THEME_LABELS[theme]}. Switch to ${THEME_LABELS[upcoming]}`}
      className="min-h-hit rounded border border-border bg-surface px-3 text-sm text-text transition-colors hover:border-accent"
    >
      Theme: {THEME_LABELS[theme]}
    </button>
  );
}
