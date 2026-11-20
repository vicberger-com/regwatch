/**
 * End-to-end tests (M0 tooling: `make e2e`; M6 acceptance 3 and 4). They run against a running
 * stack at E2E_BASE_URL (loopback by default) and sign in as the admin named in the file at
 * E2E_CREDENTIALS (lines "admin email: …" and "admin password: …"); nothing secret is in the
 * repository. Run inside the official Playwright image, as `make e2e` does.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/setup.ts",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8180",
    trace: "off",
    ...devices["Desktop Chrome"],
  },
});
