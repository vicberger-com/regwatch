/**
 * M6 acceptance 3, keyboard only: every control is reached with Tab and operated with arrow
 * keys, Enter or Space; nothing is clicked, focused or set from code. Sign in, switch the view
 * to Region and open Europe's panel, back to Country, open Germany, its latest item and the
 * Diff tab. Printing a stock report arrives with M7 and M8.
 */
import { expect, test, type Page } from "@playwright/test";

import { MARK, signInByKeyboard, tabTo } from "./session";

/** Move the active option of the focused listbox with ArrowDown until its text matches. */
async function arrowTo(page: Page, listName: RegExp, text: RegExp) {
  const list = page.getByRole("listbox", { name: listName });
  await expect(list).toBeFocused();
  await page.keyboard.press("Home");
  for (let i = 0; i < 60; i++) {
    const active = await list.getAttribute("aria-activedescendant");
    const label = active
      ? ((await page.locator(`[id="${active}"]`).textContent()) ?? "")
      : "";
    if (text.test(label)) return;
    await page.keyboard.press("ArrowDown");
  }
  throw new Error(`no option ${String(text)} in ${String(listName)}`);
}

/** Change the focused native select with the arrow keys until it shows ``label``. */
async function chooseByKeys(page: Page, name: string, label: string) {
  const select = page.getByLabel(name);
  await tabTo(page, select);
  for (let i = 0; i < 10; i++) {
    const shown = await select.evaluate(
      (el) =>
        (el as HTMLSelectElement).selectedOptions.item(0)?.textContent ?? "",
    );
    if (shown === label) return;
    await page.keyboard.press("ArrowDown");
  }
  await expect(select).toHaveValue(/./);
  throw new Error(`could not reach ${label} in ${name} with the arrow keys`);
}

test("a keyboard-only user reaches Europe, then Germany's latest item and its diff", async ({
  page,
}) => {
  await signInByKeyboard(page);
  // The map is really drawn (use testing U-M6-1).
  // The map element itself: its canvas keeps a default size even when the map box is 0 px
  // high and clips it, so the canvas alone proves nothing.
  const map = page.locator(".maplibregl-map");
  await expect(map).toBeVisible();
  expect((await map.boundingBox())?.height ?? 0).toBeGreaterThan(200);

  await chooseByKeys(page, "View", "Region");
  await tabTo(
    page,
    page.getByRole("listbox", { name: /Regions with changes/ }),
  );
  await arrowTo(page, /Regions with changes/, /Europe/);
  await page.keyboard.press("Enter");
  const europe = page.getByRole("complementary", { name: /Europe/ });
  await expect(europe.getByRole("heading", { name: /Europe/ })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(europe).toHaveCount(0);

  // Back to the View select with Shift+Tab, then the country view.
  for (let i = 0; i < 20; i++) {
    if (
      await page
        .getByLabel("View")
        .evaluate((el) => el === document.activeElement)
    )
      break;
    await page.keyboard.press("Shift+Tab");
  }
  await page.keyboard.press("ArrowUp");
  await expect(page.getByLabel("View")).toHaveValue("country");

  await tabTo(
    page,
    page.getByRole("listbox", { name: /Jurisdictions with changes/ }),
  );
  await arrowTo(page, /Jurisdictions with changes/, /Germany/);
  await page.keyboard.press("Enter");
  const panel = page.getByRole("complementary", { name: "Germany" });
  await expect(panel.getByRole("heading", { name: "Germany" })).toBeFocused();

  const latest = panel.getByRole("link", { name: new RegExp(`NIS2.*${MARK}`) });
  await latest.waitFor();
  await tabTo(page, latest, 10);
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { level: 1, name: /NIS2/ }),
  ).toBeVisible();

  await tabTo(page, page.getByRole("tab", { name: "Summary" }));
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Diff" })).toBeFocused();
  await expect(page.getByRole("tab", { name: "Diff" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  // One uploaded version has nothing to compare; the two-version diff is in the component tests.
  await expect(page.getByRole("tabpanel")).toContainText(
    /nothing to compare|lines added/,
  );
});
