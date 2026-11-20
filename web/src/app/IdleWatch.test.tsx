import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

// 20 minutes in force: the client ends a minute early (server slack) and warns a minute before.
const PREFS = { session_idle_timeout_minutes: 20 };
const MIN = 60 * 1000;

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("idle sign-out (M9 acceptance 2)", () => {
  it("keeps the warning when Stay cannot reach the server, and renews on input", async () => {
    let up = true;
    const api = fakeApi({
      "GET /auth/me": () => (up ? [200, ADMIN] : [503, { title: "down" }]),
      "GET /me/preferences": [200, PREFS],
    });
    renderAt("/me");
    await screen.findByRole("heading", { level: 1, name: "User" });
    const before = api.calls.filter((c) => c.key === "GET /auth/me").length;
    await wait(2 * MIN);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
    });
    await waitFor(() => {
      expect(api.calls.filter((c) => c.key === "GET /auth/me").length).toBe(
        before + 1,
      );
    });
    await wait(18 * MIN + 1000);
    const stay = await screen.findByRole("button", { name: "Stay signed in" });
    up = false;
    act(() => {
      stay.click();
    });
    expect(await screen.findByText(/could not be renewed/)).toHaveAttribute(
      "role",
      "alert",
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("warns before the timeout, makes the page inert, and signs out locally at zero", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /me/preferences": [200, PREFS],
      "POST /auth/logout": [503, { title: "down" }], // even when the sign-out request fails
    });
    const router = renderAt("/me");
    await screen.findByRole("heading", { level: 1, name: "User" });
    await wait(18 * MIN + 1000);
    const dialog = await screen.findByRole("alertdialog", {
      name: "You will be signed out soon",
    });
    expect(dialog).toHaveTextContent(/signed out in \d+ seconds/);
    expect(
      screen.getByRole("button", { name: "Stay signed in" }),
    ).toHaveFocus();
    // The page behind (the rendered app) is inert; the dialog is not.
    const behind = [...document.body.children].filter(
      (el) => !el.contains(dialog),
    );
    expect(behind.length).toBeGreaterThan(0);
    expect(behind.every((el) => el.hasAttribute("inert"))).toBe(true);
    expect(dialog.closest("[inert]")).toBeNull();
    await wait(61 * 1000);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/login");
    });
    expect(api.calls.some((c) => c.key === "POST /auth/logout")).toBe(true);
  });

  it("activity in this or another tab postpones the warning; Stay renews and checks", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /me/preferences": [200, PREFS],
    });
    renderAt("/me");
    await screen.findByRole("heading", { level: 1, name: "User" });
    await wait(10 * MIN);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
    });
    await wait(12 * MIN);
    expect(screen.queryByRole("alertdialog")).toBeNull(); // 12 minutes since the key
    localStorage.setItem("regwatch.activity", String(Date.now())); // another tab saw input
    await wait(10 * MIN);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await wait(8 * MIN + 30 * 1000);
    const stay = await screen.findByRole("button", { name: "Stay signed in" });
    const asked = api.calls.filter((c) => c.key === "GET /auth/me").length;
    act(() => {
      stay.click();
    });
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull();
    });
    expect(api.calls.filter((c) => c.key === "GET /auth/me").length).toBe(
      asked + 1,
    );
  });

  it("signs out when Stay finds the session already ended", async () => {
    let alive = true;
    fakeApi({
      "GET /auth/me": () =>
        alive ? [200, ADMIN] : [401, { title: "unauthenticated" }],
      "GET /me/preferences": [200, PREFS],
      "POST /auth/logout": [204, undefined],
    });
    const router = renderAt("/me");
    await screen.findByRole("heading", { level: 1, name: "User" });
    await wait(18 * MIN + 10 * 1000);
    const stay = await screen.findByRole("button", { name: "Stay signed in" });
    alive = false;
    act(() => {
      stay.click();
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/login");
    });
  });
});
