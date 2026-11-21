/**
 * BL-148 on a running stack (CP-38): a user turns on two-factor sign-in from the User tab with
 * the key shown there, keeps the recovery codes, and the next sign-in asks for a code. The
 * codes are computed here as an authenticator app would (RFC 6238). The test account is new
 * for each run and disabled at the end.
 */
import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";

import { apiSession, BASE } from "./session";

function base32(text: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of text.replace(/[\s=]/g, "").toUpperCase())
    bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const bytes = bits.match(/.{8}/g) ?? [];
  return Buffer.from(bytes.map((b) => parseInt(b, 2)));
}

/** The code for a time step, as an authenticator app computes it. */
function totp(secret: string, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const mac = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = (mac[mac.length - 1] ?? 0) & 0x0f;
  const value = (mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return value.toString().padStart(6, "0");
}

test("turns on two-factor sign-in and then needs a code to sign in (BL-148)", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const admin = await apiSession();
  const email = `mfa-e2e-${String(Date.now())}@example.org`;
  const made = await admin.post("/api/v1/admin/users", {
    data: { email, display_name: "MFA e2e", roles: ["viewer"] },
  });
  expect(made.status(), await made.text()).toBe(201);
  const { id, temporary_password: temporary } = (await made.json()) as {
    id: string;
    temporary_password: string;
  };
  const password = `e2e passphrase ${String(Date.now())}`;
  try {
    // The temporary password is changed first, through the API.
    const headers = { Origin: new URL(BASE).origin };
    const login = await page.request.post("/api/v1/auth/login", {
      headers,
      data: { email, password: temporary },
    });
    expect(login.status()).toBe(200);
    const changed = await page.request.post("/api/v1/auth/password", {
      headers,
      data: { current_password: temporary, new_password: password },
    });
    expect(changed.status()).toBe(204);

    await page.goto("/me");
    const box = page.getByRole("region", { name: "Two-factor sign-in" });
    await box.getByLabel("Password").fill(password);
    await box.getByRole("button", { name: "Set up" }).click();
    await expect(
      box.getByRole("img", { name: "QR code for your authenticator app" }),
    ).toBeVisible();
    const key = (await box.locator("code").innerText()).replace(/\s/g, "");
    const step = Math.floor(Date.now() / 30_000);
    await box
      .getByLabel("Code from your authenticator app")
      .fill(totp(key, step));
    await box.getByRole("button", { name: "Turn on" }).click();
    const codes = page.getByRole("region", { name: "Recovery codes" });
    await expect(codes.getByRole("listitem")).toHaveCount(10);
    await codes.getByRole("button", { name: "I have saved them" }).click();
    await expect(box.getByText(/10 recovery codes left/)).toBeVisible();

    await page.context().clearCookies();
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    const field = page.getByLabel("Code from your authenticator app");
    await expect(field).toBeVisible();
    await field.fill(totp(key, step + 1)); // the next step: a code is used once
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Map" }),
    ).toBeVisible();
  } finally {
    await admin.patch(`/api/v1/admin/users/${id}`, {
      data: { status: "disabled" },
    });
    await admin.dispose();
  }
});
