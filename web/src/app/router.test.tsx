import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { safeNext } from "@/features/auth/LoginPage";
import { hasPermission, loginErrorMessage } from "@/lib/auth/session";
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
      await screen.findByText(/Signed in as Ada Admin/),
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
      await screen.findByText(/Signed in as Ada Admin/),
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
      expect(screen.getByText(/Signed in as Ada Admin/)).toBeInTheDocument();
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
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Regulatory monitor",
    );
    expect(screen.getByRole("button", { name: /theme:/i })).toBeInTheDocument();
  });
});
