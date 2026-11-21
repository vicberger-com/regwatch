/**
 * No Content-Security-Policy violation on the main pages (M10.3; BL-76; M10 acceptance 2), run
 * against the production stack, whose policy has no 'unsafe-inline'. A blocked style or script
 * fails silently in the page, so every `securitypolicyviolation` event is collected.
 */
import { expect, test, type Page } from "@playwright/test";

import { signInByKeyboard } from "./session";

async function watch(page: Page): Promise<string[]> {
  const seen: string[] = [];
  await page.exposeFunction("__cspViolation", (text: string) => {
    seen.push(text);
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      (
        window as unknown as { __cspViolation: (t: string) => void }
      ).__cspViolation(
        `${e.violatedDirective} ${e.blockedURI} ${e.sourceFile}:${String(e.lineNumber)}`,
      );
    });
  });
  page.on("console", (m) => {
    if (m.text().includes("Content Security Policy"))
      seen.push(`${new URL(page.url()).pathname}: ${m.text().slice(0, 120)}`);
  });
  return seen;
}

test("the main pages run without a CSP violation", async ({ page }) => {
  test.setTimeout(120_000);
  const violations = await watch(page);
  await signInByKeyboard(page);
  for (const path of [
    "/",
    "/items",
    "/reports",
    "/outputs",
    "/me",
    "/admin",
    "/admin/settings",
    "/help",
  ]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  // The builder and its preview, which renders the report's own styles in a frame.
  await page.goto("/reports");
  await page.getByRole("button", { name: "New report", exact: true }).click();
  await expect(
    page.getByRole("form", { name: "Report settings" }),
  ).toBeVisible();
  await page
    .getByRole("form", { name: "Report settings" })
    .getByRole("button", { name: "Save", exact: true })
    .click();
  await page.getByRole("button", { name: "Preview the saved version" }).click();
  await expect(page.getByTitle("Report preview")).toBeVisible();
  await page.waitForTimeout(1_000);
  expect(violations).toEqual([]);
});
