/** M6 acceptance 4: axe reports no serious or critical issue on every route in all three themes. */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import {
  apiSession,
  MARK,
  signInByKeyboard,
  THEMES,
  useTheme,
} from "./session";

async function firstItemId(): Promise<string> {
  const api = await apiSession();
  const got = (await (
    await api.post("/api/v1/search", {
      data: { q: MARK, facet_counts: false },
    })
  ).json()) as {
    items: { id: string }[];
  };
  const id = got.items[0]?.id;
  if (!id) throw new Error("no E2E item");
  return id;
}

async function audit(page: Page, theme: string, route: string) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const bad = result.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(
    bad.map(
      (v) =>
        `${theme} ${route}: ${v.id} (${v.impact ?? ""}) ${v.nodes
          .map((n) => n.target.join(" "))
          .slice(0, 3)
          .join(" | ")}`,
    ),
  ).toEqual([]);
}

for (const theme of THEMES) {
  test(`no serious or critical axe issues in the ${theme} theme`, async ({
    page,
  }) => {
    await useTheme(page, theme);
    const id = await firstItemId();
    await signInByKeyboard(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme); // the theme applied
    const routes: [string, string][] = [
      ["/", "Map"],
      ["/items", "Items"],
      [`/items/${id}`, ""],
      ["/admin", "Settings"],
      ["/admin/sources", "Sources"],
      ["/admin/taxonomy", "Taxonomy"],
      ["/admin/users", "Users"],
      ["/legal", ""],
    ];
    for (const [route, heading] of routes) {
      await page.goto(route);
      if (heading)
        await page.getByRole("heading", { level: 1, name: heading }).waitFor();
      else await page.getByRole("heading", { level: 1 }).first().waitFor();
      await page.waitForLoadState("networkidle");
      await audit(page, theme, route);
    }
    await page.goto("/");
    await page.getByRole("radio", { name: "Table" }).check();
    await audit(page, theme, "/ (table)");
  });
}
