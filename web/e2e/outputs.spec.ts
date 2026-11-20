/**
 * The Outputs page (M8.6) in a real browser: a CSV export runs in the worker, shows Done in the
 * history, downloads through the signed link, and the page passes axe.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { signInByKeyboard } from "./session";

test("a CSV export appears in the history and downloads (M8.4, M8.6)", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await signInByKeyboard(page);
  const origin = new URL(page.url()).origin;
  const made = await page.request.post("/api/v1/outputs", {
    headers: { Origin: origin },
    data: { kind: "csv", source: { query: { columns: ["title"] } } },
  });
  expect(made.status()).toBe(202);
  const id = ((await made.json()) as { id: string }).id;

  await page.getByRole("link", { name: "Outputs" }).click();
  await expect(page.getByRole("heading", { name: "Outputs" })).toBeVisible();
  const download = page.getByRole("link", { name: /^Download CSV of query, / });
  await expect(download.first()).toBeVisible({ timeout: 60_000 }); // polled while it runs
  await expect(
    page.getByRole("row").filter({ has: download.first() }),
  ).toContainText("Done");
  const [file] = await Promise.all([
    page.waitForEvent("download"),
    download.first().click(),
  ]);
  expect(file.suggestedFilename()).toMatch(/^regwatch-.+\.csv$/);
  const kept = await page.request.get(`/api/v1/outputs/${id}`);
  expect(((await kept.json()) as { status: string }).status).toBe("sent");

  await page.getByRole("tab", { name: "Schedules" }).click();
  await expect(page.getByRole("tabpanel")).toBeVisible();
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(axe.violations).toEqual([]);
});
