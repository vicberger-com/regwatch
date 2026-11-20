/**
 * Shows the axe check is not vacuous (M6-e2e.md): a page with an unlabelled button and an image
 * without alt text must fail. Opt-in, since it only tests the tooling: E2E_CANARY=1 make e2e.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("axe reports an injected violation", async ({ page }) => {
  test.skip(process.env.E2E_CANARY !== "1", "set E2E_CANARY=1");
  await page.goto("/login");
  await page.evaluate(() => {
    document.body.append(
      document.createElement("button"),
      Object.assign(document.createElement("img"), { src: "/x.png" }),
    );
  });
  const found = await new AxeBuilder({ page }).analyze();
  expect(
    found.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    ).length,
  ).toBeGreaterThan(0);
});
