/**
 * Browser printing (M8.5) in a real browser: with print media, paper shows the page and the
 * footer's markings, but not the header or the rail, and in dark ink on white in any theme.
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
  const ink = await page
    .getByRole("main")
    .evaluate((el) => getComputedStyle(el).color);
  expect(ink).toBe("rgb(0, 0, 0)");
  await page.emulateMedia({ media: "screen" });
  await expect(page.getByRole("banner")).toBeVisible();
});
