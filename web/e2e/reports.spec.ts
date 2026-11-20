/**
 * M7.4a in a real browser: the Reports page, the lazy-loaded Puck editor actually renders
 * with the report palette, and the server preview appears in a sandboxed frame. The axe and
 * keyboard checks for the builder come with the BL-16 layer (M7.4b).
 */
import { expect, test } from "@playwright/test";

import { signInByKeyboard } from "./session";

test("a report is created, edited in Puck and previewed", async ({ page }) => {
  await signInByKeyboard(page);
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();
  await page.getByRole("button", { name: "New report", exact: true }).click();
  await expect(page).toHaveURL(/\/reports\/[0-9a-f-]{36}$/);
  const settings = page.getByRole("form", { name: "Report settings" });
  await expect(settings).toBeVisible();
  // The editor chunk loads and shows the palette and the two starting components.
  await expect(
    page.getByText("Items table", { exact: true }).first(),
  ).toBeVisible({ timeout: 20_000 });
  await expect(
    page.getByText("Latest changes", { exact: true }).first(),
  ).toBeVisible();
  const box = await page.locator("[class*='Puck']").first().boundingBox();
  expect(box?.height ?? 0).toBeGreaterThan(300); // drawn, not collapsed (the U-M6-1 lesson)
  await settings.getByRole("button", { name: "Save", exact: true }).click();
  await expect(settings.getByRole("status")).toContainText("Saved");
  await settings
    .getByRole("button", { name: "Preview the saved version" })
    .click();
  const frame = page.getByTitle("Report preview");
  await expect(frame).toHaveAttribute("sandbox", "");
  await expect(
    page
      .frameLocator("iframe[title='Report preview']")
      .getByRole("heading", { name: "New report" })
      .first(),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("builder.png"),
    fullPage: true,
  });
  // Clean up every report this journey made, including any a failed run left.
  await page.goto("/reports");
  page.on("dialog", (d) => void d.accept());
  const leftovers = page.getByRole("button", {
    name: "Delete New report",
    exact: true,
  });
  while ((await leftovers.count()) > 0) {
    await leftovers.first().click();
    await page.waitForResponse((r) => r.request().method() === "DELETE");
  }
});
