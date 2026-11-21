/**
 * Browser printing (M8.5) in a real browser: with print media, paper shows the page, its buttons as
 * text and the footer's markings, but not the header or the rail, in dark ink on white in any
 * theme; each page's margin carries the page number and the markings.
 */
import { expect, test } from "@playwright/test";

import { signInByKeyboard } from "./session";

test("the print layout keeps the page and the markings, not the frame", async ({
  page,
}) => {
  await signInByKeyboard(page);
  await page.getByRole("link", { name: "Items" }).click();
  await expect(page.getByRole("button", { name: "Print" })).toBeVisible();
  await page.emulateMedia({ media: "print", colorScheme: "dark" });
  await expect(page.getByRole("banner")).toBeHidden();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("contentinfo")).toBeVisible();
  // Buttons stay on paper as text: some carry data, such as a table's place names (review).
  const buttons = page.getByRole("main").getByRole("button");
  if ((await buttons.count()) > 0) await expect(buttons.first()).toBeVisible();
  const margin = await page.evaluate(
    () =>
      document.adoptedStyleSheets
        .flatMap((sheet) => Array.from(sheet.cssRules, (r) => r.cssText))
        .join("\n"), // a constructed sheet, which the production CSP allows (BL-76)
  );
  expect(margin).toContain("counter(pages)"); // page numbers (and markings) in every margin
  const ink = await page
    .getByRole("main")
    .evaluate((el) => getComputedStyle(el).color);
  expect(ink).toBe("rgb(0, 0, 0)");
  await page.emulateMedia({ media: "screen" });
  await expect(page.getByRole("banner")).toBeVisible();
});

test("the map prints light in the dark and high-contrast themes (U-M8-2)", async ({
  page,
}) => {
  await signInByKeyboard(page);
  await expect(page.getByRole("list", { name: "Legend" })).toBeVisible();
  for (const theme of ["dark", "high-contrast"]) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    await page.emulateMedia({ media: "print" });
    const swatch = page.locator("[data-map-swatch]").first();
    expect(
      await swatch.evaluate((el) => getComputedStyle(el).filter),
    ).toContain("invert(1)");
    const canvas = page.locator(".maplibregl-canvas");
    if ((await canvas.count()) > 0)
      expect(
        await canvas.evaluate((el) => getComputedStyle(el).filter),
      ).toContain("invert(1)");
    await page.emulateMedia({ media: "screen" });
    expect(await swatch.evaluate((el) => getComputedStyle(el).filter)).toBe(
      "none",
    );
  }
});
