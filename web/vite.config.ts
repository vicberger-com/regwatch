/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "tailwindcss";
import { defineConfig } from "vite";

import tailwindConfig from "./tailwind.config";

// React JSX is compiled by Vite's built-in esbuild ("jsx": "react-jsx" in tsconfig.app.json).
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  css: {
    postcss: { plugins: [tailwindcss(tailwindConfig)] },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // Requests arrive through the Caddy proxy (deploy/Caddyfile) as http://localhost.
    allowedHosts: ["localhost", "web"],
    hmr: { clientPort: 80 },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/test/**",
        "src/main.tsx",
        "src/**/*.d.ts",
      ],
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
    },
  },
});
