/**
 * M6 acceptance 3, keyboard only: sign in, choose the region view, open Europe, then Germany in
 * the country view, open its latest item and its Diff tab. Printing a stock report arrives with
 * M7 and M8.
 */
import { expect, test } from "@playwright/test";

import { signInByKeyboard } from "./session";

test("a keyboard-only user reaches Germany's latest item and its diff", async ({
  page,
}) => {
  await signInByKeyboard(page);
  // Region view: the map options are native selects, operated from the keyboard.
  await page.getByLabel("View").focus();
  await page.getByLabel("View").selectOption("region");
  const regions = page.getByRole("listbox", { name: /Regions with changes/ });
  await regions.focus();
  await expect(
    regions.getByRole("option", { name: /Europe/ }).first(),
  ).toBeVisible();
  // Back to countries, then Germany from the list.
  await page.getByLabel("View").focus();
  await page.getByLabel("View").selectOption("country");
  const list = page.getByRole("listbox", {
    name: /Jurisdictions with changes/,
  });
  await list.focus();
  for (let i = 0; i < 20; i++) {
    const active = await list.getAttribute("aria-activedescendant");
    const text = active
      ? await page.locator(`[id="${active}"]`).textContent()
      : "";
    if (text?.includes("Germany")) break;
    await page.keyboard.press("ArrowDown");
  }
  await page.keyboard.press("Enter");
  const panel = page.getByRole("complementary", { name: "Germany" });
  await expect(panel.getByRole("heading", { name: "Germany" })).toBeFocused();
  // Into the panel's latest change, by Tab and Enter.
  const latest = panel.getByRole("link", { name: /E2E: NIS2/ });
  await latest.waitFor();
  for (
    let i = 0;
    i < 10 && !(await latest.evaluate((el) => el === document.activeElement));
    i++
  ) {
    await page.keyboard.press("Tab");
  }
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { level: 1, name: /E2E: NIS2/ }),
  ).toBeVisible();
  // The tabs: Tab into the tab list, arrow to Diff.
  const summary = page.getByRole("tab", { name: "Summary" });
  for (
    let i = 0;
    i < 20 && !(await summary.evaluate((el) => el === document.activeElement));
    i++
  ) {
    await page.keyboard.press("Tab");
  }
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Diff" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("tabpanel")).toContainText(
    /nothing to compare|lines added/,
  );
});
