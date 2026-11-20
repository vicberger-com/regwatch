/**
 * M7.4a in a real browser: the Reports page, the lazy-loaded Puck editor actually renders
 * with the report palette, and the server preview appears in a sandboxed frame. The axe and
 * keyboard checks for the builder come with the BL-16 layer (M7.4b).
 */
import AxeBuilder from "@axe-core/playwright";
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
    page.locator("[data-report-editor] [data-puck-component]").first(),
  ).toBeVisible({ timeout: 20_000 });
  await expect(page.getByLabel("Add a component")).toBeVisible();
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

test("the builder works by keyboard alone and passes axe (BL-16)", async ({
  page,
}) => {
  await signInByKeyboard(page);
  await page.goto("/reports");
  await page.getByRole("button", { name: "New report", exact: true }).click();
  await expect(
    page.locator("[data-report-editor] [data-puck-component]").first(),
  ).toBeVisible({ timeout: 20_000 });
  const items = page.locator("[data-report-editor] [data-puck-component]");
  const order = async () =>
    Promise.all(
      (await items.all()).map(async (i) => (await i.innerText()).slice(0, 12)),
    );
  await expect(items).toHaveCount(2);

  // Insert by keyboard: focus the picker, choose Paragraph with the arrow keys, Tab, Enter.
  const picker = page.getByLabel("Add a component");
  await picker.focus();
  await picker.selectOption({ label: "Paragraph" });
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Add", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(items).toHaveCount(3);
  await expect(
    page.locator("[data-report-editor] > [role=status]"),
  ).toContainText("Paragraph added");

  // Select by keyboard, then move it up with the action bar's button.
  const before = await order();
  await items.nth(2).focus();
  await page.keyboard.press("Enter");
  const up = page.getByRole("button", { name: "Move up" });
  await up.focus();
  await page.keyboard.press("Enter");
  await expect.poll(order).not.toEqual(before);
  expect((await order())[1]).toBe(before[2]);
  await expect(
    page.locator("[data-report-editor] > [role=status]"),
  ).toContainText("Moved to position 2 of 3");

  const found = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(
    found.violations
      .filter((v) => v.impact === "serious" || v.impact === "critical")
      .map(
        (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
      ),
  ).toEqual([]);

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

test("a report becomes a PDF through Gotenberg within two minutes (M8 acceptance 1)", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signInByKeyboard(page);
  const origin = new URL(page.url()).origin;
  const headers = { Origin: origin };
  const made = await page.request.post("/api/v1/outputs", {
    headers,
    data: {
      kind: "pdf",
      source: { report_template_key: "regulation-status-matrix" },
    },
  });
  expect(made.status()).toBe(202);
  const id = ((await made.json()) as { id: string }).id;
  const started = Date.now();
  let status = "queued";
  while (
    Date.now() - started < 120_000 &&
    (status === "queued" || status === "rendering")
  ) {
    await page.waitForTimeout(2_000);
    const job = (await (
      await page.request.get(`/api/v1/outputs/${id}`)
    ).json()) as {
      status: string;
      error_class: string | null;
    };
    status = job.status;
    expect(job.error_class).toBeNull();
  }
  expect(status).toBe("sent");
  const file = await page.request.get(`/api/v1/outputs/${id}/artifact`);
  expect(file.status()).toBe(200);
  expect(file.headers()["content-type"]).toBe("application/pdf");
  const body = await file.body();
  expect(body.subarray(0, 5).toString()).toBe("%PDF-");
  const pages =
    body.toString("latin1").match(/\/Type\s*\/Page(?![a-zA-Z])/g) ?? [];
  expect(pages.length).toBeGreaterThan(0);
});

test("a stock report is emailed with its PDF and arrives in Mailpit (M8 acceptance 2)", async ({
  page,
}) => {
  const mailpit = process.env.E2E_MAILPIT_URL;
  test.skip(!mailpit, "set E2E_MAILPIT_URL to the stack's Mailpit");
  test.setTimeout(180_000);
  await signInByKeyboard(page);
  const headers = { Origin: new URL(page.url()).origin };
  const setting = "/api/v1/admin/settings/outputs.allowed_recipient_domains";
  const before = (
    (await (await page.request.get(setting)).json()) as { value: string[] }
  ).value;
  await page.request.put(setting, {
    headers,
    data: { value: ["example.org"] },
  });
  try {
    const subject = `regwatch e2e ${String(Date.now())}`;
    const made = await page.request.post("/api/v1/outputs", {
      headers,
      data: {
        kind: "email",
        source: { report_template_key: "source-health" },
        destination: {
          emails: ["one@example.org", "two@example.org"],
          subject,
        },
      },
    });
    expect(made.status()).toBe(202);
    const id = ((await made.json()) as { id: string }).id;
    await expect
      .poll(
        async () =>
          (
            (await (
              await page.request.get(`/api/v1/outputs/${id}`)
            ).json()) as { status: string }
          ).status,
        { timeout: 120_000, intervals: [2_000] },
      )
      .toBe("sent");
    const found = (await (
      await page.request.get(
        `${String(mailpit)}/api/v1/search?query=${encodeURIComponent(`subject:"${subject}"`)}`,
      )
    ).json()) as {
      messages: { To: { Address: string }[]; Attachments: number }[];
    };
    expect(found.messages.map((m) => m.To[0]?.Address).sort()).toEqual([
      "one@example.org",
      "two@example.org",
    ]);
    expect(found.messages.every((m) => m.Attachments === 1)).toBe(true);
  } finally {
    await page.request.put(setting, { headers, data: { value: before } });
  }
});
