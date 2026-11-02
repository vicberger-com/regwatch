// Theme state: html[data-theme] plus localStorage until M9 moves it to server preferences.
export const THEMES = ["light", "dark", "high-contrast"] as const;
export type Theme = (typeof THEMES)[number];

export const THEME_STORAGE_KEY = "regwatch.theme";

export const THEME_LABELS: Record<Theme, string> = {
  light: "Light",
  dark: "Dark",
  "high-contrast": "High contrast",
};

export function isTheme(value: unknown): value is Theme {
  return (
    typeof value === "string" && (THEMES as readonly string[]).includes(value)
  );
}

export function nextTheme(theme: Theme): Theme {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length] ?? "light";
}

function defaultStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null; // reading localStorage itself throws when storage is blocked
  }
}

export function readStoredTheme(
  storage: Storage | null = defaultStorage(),
): Theme {
  if (storage === null) return "light";
  try {
    const value = storage.getItem(THEME_STORAGE_KEY);
    return isTheme(value) ? value : "light";
  } catch {
    return "light";
  }
}

export function applyTheme(
  theme: Theme,
  root: HTMLElement = document.documentElement,
  storage: Storage | null = defaultStorage(),
): void {
  root.dataset.theme = theme;
  try {
    storage?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // The theme still applies for this page view.
  }
}
