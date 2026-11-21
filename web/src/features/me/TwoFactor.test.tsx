import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

const BASE = {
  "GET /auth/me": [200, ADMIN] as [number, unknown],
  "GET /me/sessions": [200, []] as [number, unknown],
  "GET /views": [200, []] as [number, unknown],
};
const CODES = Array.from({ length: 10 }, (_, i) => `abcde-fgh${String(i)}k`);

afterEach(() => {
  vi.unstubAllGlobals();
});

async function section() {
  renderAt("/me");
  return within(
    await screen.findByRole("region", { name: "Two-factor sign-in" }),
  );
}

describe("two-factor sign-in on the user tab (BL-148)", () => {
  it("sets up with the password, a QR code and a first code, then shows the recovery codes once", async () => {
    let on = false;
    const api = fakeApi({
      ...BASE,
      "GET /me/mfa": () => [
        200,
        on
          ? {
              enabled: true,
              confirmed_at: "2026-11-21T10:00:00Z",
              recovery_codes_left: 10,
            }
          : { enabled: false, recovery_codes_left: 0 },
      ],
      "POST /me/mfa/setup": [
        200,
        {
          secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
          otpauth_uri: "otpauth://totp/x",
          qr: ["101", "010", "101"],
        },
      ],
      "POST /me/mfa/confirm": () => {
        on = true;
        return [200, { recovery_codes: CODES }];
      },
    });
    const user = userEvent.setup();
    const box = await section();
    await user.type(await box.findByLabelText("Password"), "my password 1234");
    await user.click(box.getByRole("button", { name: "Set up" }));
    expect(
      await box.findByRole("img", {
        name: "QR code for your authenticator app",
      }),
    ).toBeInTheDocument();
    expect(
      box.getByText("JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP"),
    ).toBeInTheDocument();
    await user.type(
      box.getByLabelText("Code from your authenticator app"),
      "123456",
    );
    await user.click(box.getByRole("button", { name: "Turn on" }));
    const list = await screen.findByRole("region", { name: "Recovery codes" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(10);
    expect(api.calls.find((c) => c.key === "POST /me/mfa/setup")?.body).toEqual(
      {
        password: "my password 1234",
      },
    );
    expect(
      api.calls.find((c) => c.key === "POST /me/mfa/confirm")?.body,
    ).toEqual({
      code: "123456",
    });
    await user.click(
      within(list).getByRole("button", { name: "I have saved them" }),
    );
    expect(await box.findByText(/10 recovery codes left/)).toBeInTheDocument();
  });

  it("shows a wrong password without leaving the form", async () => {
    fakeApi({
      ...BASE,
      "POST /me/mfa/setup": [400, problem(400, "The password is incorrect.")],
    });
    const user = userEvent.setup();
    const box = await section();
    await user.type(await box.findByLabelText("Password"), "wrong");
    await user.click(box.getByRole("button", { name: "Set up" }));
    expect(await box.findByRole("alert")).toHaveTextContent(
      "The password is incorrect.",
    );
  });

  it("turns off with the password and a code", async () => {
    let on = true;
    const api = fakeApi({
      ...BASE,
      "GET /me/mfa": () => [
        200,
        on
          ? { enabled: true, confirmed_at: null, recovery_codes_left: 3 }
          : { enabled: false, recovery_codes_left: 0 },
      ],
      "POST /me/mfa/disable": () => {
        on = false;
        return [204, undefined];
      },
    });
    const user = userEvent.setup();
    const box = await section();
    await user.click(await box.findByRole("button", { name: "Turn off" }));
    const form = box.getByRole("form", { name: "Turn off two-factor sign-in" });
    await user.type(
      within(form).getByLabelText("Password"),
      "my password 1234",
    );
    await user.type(
      within(form).getByLabelText("Code from your authenticator app"),
      "654321",
    );
    await user.click(within(form).getByRole("button", { name: "Turn off" }));
    expect(
      await box.findByRole("button", { name: "Set up" }),
    ).toBeInTheDocument();
    expect(
      api.calls.find((c) => c.key === "POST /me/mfa/disable")?.body,
    ).toEqual({
      password: "my password 1234",
      code: "654321",
    });
  });
});
