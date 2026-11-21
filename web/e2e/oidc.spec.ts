/**
 * M1b on the QA stack (BL-147; CP-37): with `auth.oidc` on and the `oidc-test` profile's
 * Keycloak, a person with an account signs in with the organisation's account, and someone the
 * provider does not vouch for with a verified email is turned back. The flag is restored at
 * the end. Runs only where E2E_OIDC_ENV names the profile's keycloak.env (for the test users'
 * password; scripts/oidc-test-env.sh).
 */
import { readFileSync } from "node:fs";

import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

import { apiSession } from "./session";

const env = process.env.E2E_OIDC_ENV;
test.skip(!env, "needs the oidc-test profile (QA)");

function userPassword(): string {
  const text = readFileSync(env ?? "", "utf8");
  return /^KC_USER_PASSWORD=(.+)$/m.exec(text)?.[1]?.trim() ?? "";
}

async function ensureUser(api: APIRequestContext, email: string, name: string) {
  const made = await api.post("/api/v1/admin/users", {
    data: { email, display_name: name, roles: ["viewer"] },
  });
  expect([201, 409], await made.text()).toContain(made.status()); // 409: an earlier run's
}

async function signInAtProvider(page: Page, username: string) {
  await page.goto("/login");
  await page
    .getByRole("link", { name: "Sign in with your organisation's account" })
    .click();
  await page.waitForURL(/^http:\/\/idp\.localhost:8190\//);
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(userPassword());
  await page.getByRole("button", { name: "Sign In" }).click();
}

test("signs in with the organisation's account, and turns back the unverified (M1b)", async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const api = await apiSession();
  const flag = (enabled: boolean) =>
    api.patch("/api/v1/admin/feature-flags/auth.oidc", { data: { enabled } });
  await ensureUser(api, "oidc-user@example.org", "OIDC User");
  await ensureUser(api, "oidc-unverified@example.org", "Unverified User");
  expect((await flag(true)).status()).toBe(200);
  try {
    // A fresh context each time, so the provider's own session does not carry over.
    const first = await browser.newContext();
    const page = await first.newPage();
    await signInAtProvider(page, "oidc-user");
    await expect(
      page.getByRole("heading", { level: 1, name: "Map" }),
    ).toBeVisible();
    const me = await page.request.get("/api/v1/auth/me");
    expect(((await me.json()) as { email: string }).email).toBe(
      "oidc-user@example.org",
    );
    await first.close();

    const second = await browser.newContext();
    const other = await second.newPage();
    await signInAtProvider(other, "oidc-unverified");
    await other.waitForURL(/\/login\?sso=unknown/);
    await expect(other.getByRole("alert")).toHaveText(
      /There is no account for you here yet/,
    );
    expect((await other.request.get("/api/v1/auth/me")).status()).toBe(401);
    await second.close();
  } finally {
    expect((await flag(false)).status()).toBe(200);
    await api.dispose();
  }
});
