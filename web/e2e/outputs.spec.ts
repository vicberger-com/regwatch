/**
 * The Outputs page (M8.6) in a real browser: a CSV export requested with the New output form
 * runs in the worker, shows Done in the history, downloads through the signed link, and the
 * page passes axe.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { signInByKeyboard } from "./session";

test("a CSV export appears in the history and downloads (M8.4, M8.6)", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await signInByKeyboard(page);
  await page.getByRole("link", { name: "Outputs" }).click();
  await expect(page.getByRole("heading", { name: "Outputs" })).toBeVisible();
  await page.getByRole("button", { name: "New output" }).click();
  const form = page.getByRole("form", { name: "New output" });
  await form.getByRole("combobox", { name: "What" }).selectOption("csv");
  await form.getByRole("combobox", { name: "Items" }).selectOption("all");
  await form.getByRole("button", { name: "Request" }).click();
  await expect(form.getByRole("status")).toContainText("Requested.");
  // The newest row is this request: Done once the worker has written it (polled meanwhile).
  const newest = page.getByRole("tabpanel").getByRole("row").nth(1);
  await expect(newest).toContainText("Done", { timeout: 60_000 });
  const download = newest.getByRole("link", {
    name: /^Download CSV of all items, /,
  });
  const [file] = await Promise.all([
    page.waitForEvent("download"),
    download.click(),
  ]);
  expect(file.suggestedFilename()).toMatch(/^regwatch-.+\.csv$/);

  await page.getByRole("tab", { name: "Schedules" }).click();
  await expect(page.getByRole("tabpanel")).toBeVisible();
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(axe.violations).toEqual([]);
});
