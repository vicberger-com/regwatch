import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { safeNext } from "@/features/auth/LoginPage";
import {
  hasPermission,
  loginErrorMessage,
  ssoErrorMessage,
} from "@/lib/auth/session";
import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

async function signIn(password = "correct horse battery") {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Email"), "admin@example.org");
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return user;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sign-in flow", () => {
  it("offers the organisation's account when SSO is on (M1b)", async () => {
    fakeApi({
      "GET /auth/me": [401, problem(401)],
      "GET /auth/sso": [200, { enabled: true }],
    });
    renderAt("/login?next=%2Fitems");
    const link = await screen.findByRole("link", {
      name: "Sign in with your organisation's account",
    });
    expect(link).toHaveAttribute(
      "href",
      "/api/v1/auth/oidc/login?next=%2Fitems",
    );
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("hides it when SSO is off, and never forwards another site", async () => {
    fakeApi({ "GET /auth/me": [401, problem(401)] });
    renderAt("/login");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(
      screen.queryByRole("link", { name: /organisation/ }),
    ).not.toBeInTheDocument();
  });

  it("explains why the provider's sign-in came back", async () => {
    fakeApi({
      "GET /auth/me": [401, problem(401)],
      "GET /auth/sso": [200, { enabled: true }],
    });
    renderAt("/login?sso=unknown");
    expect(
      await screen.findByText(/There is no account for you here yet/),
    ).toHaveAttribute("role", "alert");
  });

  it("asks for the authenticator code after a right password (BL-148)", async () => {
    const api = fakeApi({
      "GET /auth/me": [401, problem(401)],
      "POST /auth/login": [
        401,
        { ...problem(401), type: "https://regwatch/errors/mfa-required" },
      ],
      "POST /auth/mfa": (body) =>
        (body as { code: string }).code === "123456"
          ? [200, ADMIN]
          : [
              401,
              {
                ...problem(401, "The code is not valid. Enter a new one."),
                type: "https://regwatch/errors/mfa-invalid",
              },
            ],
    });
    renderAt("/login?next=%2Fitems");
    const user = await signIn();
    const field = await screen.findByLabelText(
      "Code from your authenticator app",
    );
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    await user.type(field, "000000");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The code is not valid.",
    );
    await user.clear(field);
    await user.type(field, " 123456 ");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Items" }),
    ).toBeInTheDocument();
    expect(
      api.calls.filter((c) => c.key === "POST /auth/mfa").map((c) => c.body),
    ).toEqual([{ code: "000000" }, { code: "123456" }]);
  });

  it("tells non-administrators to use the organisation's account", async () => {
    fakeApi({
      "GET /auth/me": [401, problem(401)],
      "GET /auth/sso": [200, { enabled: true }],
      "POST /auth/login": [
        403,
        {
          ...problem(403),
          type: "https://regwatch.example/problems/sso-required",
        },
      ],
    });
    renderAt("/login");
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign in with your organisation's account.",
    );
  });

  it("sends anonymous visitors to the login page and back after signing in", async () => {
    const api = fakeApi({
      "GET /auth/me": [401, problem(401)],
      "POST /auth/login": [200, ADMIN],
    });
    const router = renderAt("/");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(router.state.location.search).toEqual({ next: "/" });
    await signIn();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Map" }),
    ).toBeInTheDocument();
    const login = api.calls.find((c) => c.key === "POST /auth/login");
    expect(login?.body).toEqual({
      email: "admin@example.org",
      password: "correct horse battery",
      remember_me: false,
    });
  });

  it("announces a wrong password without saying whether the email exists", async () => {
    fakeApi({
      "GET /auth/me": [401, problem(401)],
      "POST /auth/login": [401, problem(401)],
    });
    renderAt("/login");
    await signIn("wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The email or password is incorrect.",
    );
  });

  it("forces a temporary password to be changed, checking it first", async () => {
    let me: unknown = { ...ADMIN, must_change_password: true };
    fakeApi({
      "GET /auth/me": () => [200, me],
      "POST /auth/login": () => [200, me],
      "POST /auth/password": () => {
        me = { ...ADMIN, must_change_password: false };
        return [204, undefined];
      },
    });
    renderAt("/login");
    const user = await signIn("temporary-pass");
    await screen.findByRole("heading", { name: "Change password" });
    expect(screen.getByText(/temporary password/)).toBeInTheDocument();
    await user.type(
      screen.getByLabelText("Current password"),
      "temporary-pass",
    );
    await user.type(screen.getByLabelText(/New password/), "short");
    await user.type(screen.getByLabelText("Repeat new password"), "short");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "at least 12 characters",
    );
    await user.clear(screen.getByLabelText(/New password/));
    await user.type(
      screen.getByLabelText(/New password/),
      "a long new passphrase",
    );
    await user.clear(screen.getByLabelText("Repeat new password"));
    await user.type(
      screen.getByLabelText("Repeat new password"),
      "a different passphrase",
    );
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByRole("alert")).toHaveTextContent("do not match");
    await user.clear(screen.getByLabelText("Repeat new password"));
    await user.type(
      screen.getByLabelText("Repeat new password"),
      "a long new passphrase",
    );
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Map" }),
    ).toBeInTheDocument();
  });

  it("shows the server's reason when a password change is refused", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "POST /auth/password": [
        400,
        problem(400, "The current password is incorrect."),
      ],
    });
    renderAt("/change-password");
    const user = userEvent.setup();
    await user.type(
      await screen.findByLabelText("Current password"),
      "not it at all",
    );
    await user.type(
      screen.getByLabelText(/New password/),
      "a long new passphrase",
    );
    await user.type(
      screen.getByLabelText("Repeat new password"),
      "a long new passphrase",
    );
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The current password is incorrect.",
    );
  });

  it("signs out and returns to the login page", async () => {
    let me: unknown = ADMIN;
    fakeApi({
      "GET /auth/me": () => (me ? [200, me] : [401, problem(401)]),
      "POST /auth/logout": () => {
        me = null;
        return [204, undefined];
      },
    });
    renderAt("/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    await screen.findByRole("heading", { name: "Sign in" });
  });
});

describe("session helpers", () => {
  it("maps documented sign-in answers to messages", () => {
    expect(loginErrorMessage(problem(423))).toMatch(/locked/);
    expect(loginErrorMessage(problem(429))).toMatch(/Too many/);
    expect(loginErrorMessage(problem(500, "Boom"))).toBe("Boom");
    expect(loginErrorMessage(problem(500))).toBe("Sign-in failed. Try again.");
    expect(ssoErrorMessage(undefined)).toBe("");
    for (const reason of ["inactive", "state", "provider", "refused", "token"])
      expect(ssoErrorMessage(reason)).not.toBe("");
  });

  it("follows only same-site paths after sign-in", () => {
    expect(safeNext("/admin/users")).toBe("/admin/users");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext(undefined)).toBe("/");
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext("/ok\tthen")).toBe("/");
  });

  it("reads permissions from the signed-in user", () => {
    expect(hasPermission(ADMIN as never, "users.manage")).toBe(true);
    expect(hasPermission(null, "users.manage")).toBe(false);
  });
});

describe("guard", () => {
  it("waits for the session before rendering a protected page", async () => {
    fakeApi({ "GET /auth/me": [200, ADMIN] });
    renderAt("/");
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { level: 1, name: "Map" }),
      ).toBeInTheDocument();
    });
  });
});

describe("AppShell", () => {
  it("renders the landmarks, a skip link and the theme switch when signed in", async () => {
    fakeApi({ "GET /auth/me": [200, ADMIN] });
    renderAt("/");
    expect(await screen.findByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(
      screen.getByRole("link", { name: /skip to main content/i }),
    ).toHaveAttribute("href", "#main");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Map");
    expect(screen.getByRole("button", { name: /theme:/i })).toBeInTheDocument();
  });
});
