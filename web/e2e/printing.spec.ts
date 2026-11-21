/**
 * M8 acceptance 3 on the QA stack (CP-33): with the print flag on and the `print-test`
 * profile's ippeveprinter, a print job reaches the printer and the output shows sent. The
 * settings changed here are restored at the end. Runs only where E2E_PRINT_TEST is set.
 */
import { expect, test } from "@playwright/test";

import { signInByKeyboard } from "./session";

test.skip(!process.env.E2E_PRINT_TEST, "needs the print-test profile (QA)");

test("a report reaches the test printer and shows sent (M8 acceptance 3)", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signInByKeyboard(page);
  const headers = { Origin: new URL(page.url()).origin };
  const setting = (key: string, value: unknown) =>
    page.request.put(`/api/v1/admin/settings/${key}`, {
      headers,
      data: { value },
    });
  const flag = (enabled: boolean) =>
    page.request.patch("/api/v1/admin/feature-flags/outputs.server_print", {
      headers,
      data: { enabled },
    });
  expect((await flag(true)).status()).toBe(200);
  expect((await setting("outputs.printer_plain_ipp", true)).status()).toBe(200); // the test printer has no TLS
  let printer = "";
  try {
    const made = await page.request.post("/api/v1/admin/printers", {
      headers,
      data: {
        name: `QA test printer ${String(Date.now())}`,
        ipp_url: "ipp://ippeveprinter:631/ipp/print",
      },
    });
    expect(made.status(), await made.text()).toBe(201);
    printer = ((await made.json()) as { id: string }).id;

    await page.getByRole("link", { name: "Outputs" }).click();
    await page.getByRole("button", { name: "New output" }).click();
    const form = page.getByRole("form", { name: "New output" });
    await form.getByRole("combobox", { name: "What" }).selectOption("print");
    await form
      .getByRole("combobox", { name: "Report" })
      .selectOption({ label: "Source health" });
    await form.getByRole("combobox", { name: "Printer" }).selectOption(printer);
    await form.getByRole("button", { name: "Request" }).click();
    await expect(form.getByRole("status")).toContainText("Requested.");
    const newest = page.getByRole("tabpanel").getByRole("row").nth(1);
    await expect(newest).toContainText("Done", { timeout: 120_000 });
    await expect(newest).toContainText("printer, 1 copies");
  } finally {
    if (printer)
      await page.request.delete(`/api/v1/admin/printers/${printer}`, {
        headers,
      });
    await setting("outputs.printer_plain_ipp", false);
    await flag(false);
  }
});
