import type { Config } from "tailwindcss";

// Every colour, radius and size comes from src/styles/tokens.css, so the three themes
// switch by changing html[data-theme] alone.
const token = (name: string) => `var(--${name})`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      bg: token("bg"),
      surface: token("surface"),
      border: token("border"),
      text: token("text"),
      "text-muted": token("text-muted"),
      accent: token("accent"),
      "accent-contrast": token("accent-contrast"),
      good: token("good"),
      warning: token("warning"),
      critical: token("critical"),
      focus: token("focus"),
      "map-0": token("map-0"),
      "map-1": token("map-1"),
      "map-2": token("map-2"),
      "map-3": token("map-3"),
      "map-4": token("map-4"),
    },
    fontFamily: { sans: token("font-sans") },
    fontSize: {
      xs: token("text-xs"),
      sm: token("text-sm"),
      base: token("text-base"),
      lg: token("text-lg"),
      xl: token("text-xl"),
      "2xl": token("text-2xl"),
    },
    fontWeight: { normal: "400", semibold: "600" },
    lineHeight: { normal: token("leading") },
    borderRadius: { none: "0", DEFAULT: token("radius"), full: "9999px" },
    borderWidth: { 0: "0", DEFAULT: token("border-width") },
    boxShadow: { none: "none", menu: token("shadow-menu") },
    extend: {
      spacing: {
        1: token("space-1"),
        2: token("space-2"),
        3: token("space-3"),
        4: token("space-4"),
        6: token("space-6"),
        8: token("space-8"),
        12: token("space-12"),
      },
      minHeight: { hit: token("hit-target") },
      minWidth: { hit: token("hit-target") },
      transitionDuration: { DEFAULT: token("motion-duration") },
    },
  },
  plugins: [],
} satisfies Config;
