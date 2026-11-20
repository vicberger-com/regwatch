import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

const PREFS = { session_idle_timeout_minutes: 20 };

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("idle sign-out (M9 acceptance 2)", () => {
  it("warns 60 seconds before the timeout, announces the countdown, and signs out at zero", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /me/preferences": [200, PREFS],
      "POST /auth/logout": [204, undefined],
    });
    renderAt("/me");
    await screen.findByRole("heading", { level: 1, name: "User" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(19 * 60 * 1000 + 1000);
    });
    const dialog = await screen.findByRole("alertdialog", {
      name: "You will be signed out soon",
    });
    expect(dialog).toHaveTextContent(/signed out in \d+ seconds/);
    expect(
      screen.getByRole("button", { name: "Stay signed in" }),
    ).toHaveFocus();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61 * 1000);
    });
    await waitFor(() => {
      expect(api.calls.some((c) => c.key === "POST /auth/logout")).toBe(true);
    });
  });

  it("stays signed in when asked, and activity postpones the warning", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /me/preferences": [200, PREFS],
    });
    renderAt("/me");
    await screen.findByRole("heading", { level: 1, name: "User" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(12 * 60 * 1000);
    });
    expect(screen.queryByRole("alertdialog")).toBeNull(); // 12 minutes since the key, not 22
    await act(async () => {
      await vi.advanceTimersByTimeAsync(7 * 60 * 1000 + 30 * 1000);
    });
    const stay = await screen.findByRole("button", { name: "Stay signed in" });
    const asked = api.calls.filter((c) => c.key === "GET /auth/me").length;
    act(() => {
      stay.click();
    });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => {
      expect(api.calls.filter((c) => c.key === "GET /auth/me").length).toBe(
        asked + 1,
      );
    });
    expect(api.calls.some((c) => c.key === "POST /auth/logout")).toBe(false);
  });
});
