/** Sign-in helpers for the end-to-end tests: credentials come from E2E_CREDENTIALS only. */
import { readFileSync } from "node:fs";

import {
  expect,
  request,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";

export function credentials(): { email: string; password: string } {
  const path = process.env.E2E_CREDENTIALS;
  if (!path)
    throw new Error("set E2E_CREDENTIALS to the stack's admin credential file");
  const text = readFileSync(path, "utf8");
  const field = (name: string) =>
    new RegExp(`${name}: *(.+)`).exec(text)?.[1]?.trim() ?? "";
  return { email: field("admin email"), password: field("admin password") };
}

function base(): string {
  const url = process.env.E2E_BASE_URL;
  if (!url) throw new Error("set E2E_BASE_URL to the stack under test");
  const loopback = /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/?$/.test(url);
  if (
    !loopback &&
    !(process.env.E2E_ALLOW_REMOTE === "1" && url.startsWith("https://"))
  ) {
    throw new Error(
      "only a loopback stack, or an https one with E2E_ALLOW_REMOTE=1",
    );
  }
  return url;
}

export const BASE = base();

/** The marker in every fixture title, so tests never pick up a real item. */
export const MARK = "regwatch-e2e-fixture";

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

/** Press Tab until ``target`` has focus (at most ``max`` presses); fails otherwise. */
export async function tabTo(
  page: Page,
  target: Locator,
  max = 40,
): Promise<void> {
  for (let i = 0; i < max; i++) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  await expect(target).toBeFocused();
}

/** Sign in through the form with the keyboard only (M6 acceptance 3). */
export async function signInByKeyboard(page: Page): Promise<void> {
  const { email, password } = credentials();
  await page.goto("/login");
  await tabTo(page, page.getByLabel("Email"));
  await page.keyboard.type(email);
  await page.keyboard.press("Tab");
  await page.keyboard.type(password);
  await page.keyboard.press("Enter");
  await page.getByRole("heading", { level: 1, name: "Map" }).waitFor();
}

export const THEMES = ["light", "dark", "high-contrast"] as const;

/**
 * Use a theme: saved in the admin's preferences, which the shell applies after sign-in (M9),
 * and in localStorage for the first paint. Returns a function that restores "system".
 */
export async function useTheme(
  page: Page,
  theme: (typeof THEMES)[number],
): Promise<() => Promise<void>> {
  const api = await apiSession();
  const set = await api.patch("/api/v1/me/preferences", { data: { theme } });
  if (!set.ok())
    throw new Error(`setting the theme: HTTP ${String(set.status())}`);
  await page.addInitScript((t) => {
    window.localStorage.setItem("regwatch.theme", t);
  }, theme);
  return async () => {
    await api.patch("/api/v1/me/preferences", { data: { theme: "system" } });
    await api.dispose();
  };
}
