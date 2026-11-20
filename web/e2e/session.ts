/** Sign-in helpers for the end-to-end tests: credentials come from E2E_CREDENTIALS only. */
import { readFileSync } from "node:fs";

import { request, type APIRequestContext, type Page } from "@playwright/test";

export function credentials(): { email: string; password: string } {
  const path = process.env.E2E_CREDENTIALS;
  if (!path)
    throw new Error("set E2E_CREDENTIALS to the stack's admin credential file");
  const text = readFileSync(path, "utf8");
  const field = (name: string) =>
    new RegExp(`${name}: *(.+)`).exec(text)?.[1]?.trim() ?? "";
  return { email: field("admin email"), password: field("admin password") };
}

export const BASE = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8180";

/** An API session signed in as the admin; the Origin header is the one the API expects. */
export async function apiSession(): Promise<APIRequestContext> {
  const api = await request.newContext({
    baseURL: BASE,
    extraHTTPHeaders: { Origin: BASE },
  });
  const { email, password } = credentials();
  const got = await api.post("/api/v1/auth/login", {
    data: { email, password },
  });
  if (!got.ok())
    throw new Error(`sign-in failed: HTTP ${String(got.status())}`);
  return api;
}

/** Sign in through the form with the keyboard only (M6 acceptance 3). */
export async function signInByKeyboard(page: Page): Promise<void> {
  const { email, password } = credentials();
  await page.goto("/login");
  await page.getByLabel("Email").focus();
  await page.keyboard.type(email);
  await page.keyboard.press("Tab");
  await page.keyboard.type(password);
  await page.keyboard.press("Enter");
  await page.getByRole("heading", { level: 1, name: "Map" }).waitFor();
}

export const THEMES = ["light", "dark", "high-contrast"] as const;

/** Start a page in a theme (the shell reads it from localStorage until M9). */
export async function useTheme(
  page: Page,
  theme: (typeof THEMES)[number],
): Promise<void> {
  await page.addInitScript((t) => {
    window.localStorage.setItem("regwatch.theme", t);
  }, theme);
}
