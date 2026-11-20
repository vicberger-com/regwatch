import { useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { meQuery } from "@/lib/auth/session";

import {
  applyTheme,
  isTheme,
  nextTheme,
  readStoredTheme,
  THEME_LABELS,
  type Theme,
} from "./theme";

function currentTheme(): Theme {
  const shown = document.documentElement.dataset.theme;
  return isTheme(shown) ? shown : readStoredTheme();
}

function subscribeTheme(onChange: () => void): () => void {
  const watch = new MutationObserver(onChange);
  watch.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => {
    watch.disconnect();
  };
}

export function ThemeSwitch() {
  // The theme on screen, whoever set it (this button, the user tab, preferences on sign-in):
  // the button never disagrees with the page (use testing finding).
  const theme = useSyncExternalStore(
    subscribeTheme,
    currentTheme,
    readStoredTheme,
  );
  const upcoming = nextTheme(theme);
  const client = useQueryClient();

  function cycle() {
    applyTheme(upcoming);
    // Saved to the user's preferences when signed in, so other devices follow (M9).
    if (client.getQueryData(meQuery.queryKey)) {
      const body = { theme: upcoming } as Schemas["Preferences"]; // a partial PATCH
      void api
        .PATCH("/me/preferences", { body })
        .then(() => client.invalidateQueries({ queryKey: meQuery.queryKey }))
        .catch(() => undefined); // the theme still applies here; the next save retries
    }
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
