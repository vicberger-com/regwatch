import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

const PREFS = {
  theme: "system",
  accessibility_preset: false,
  font_scale: 100,
  density: "default",
  reduced_motion: "system",
  toolbar_labels: "hover",
  locale: "en",
  timezone: "UTC",
  landing_view_id: null,
  session_idle_timeout_minutes: 480,
  remember_me_default: false,
};
const SESSIONS = [
  {
    id: "0190a000-0000-7000-8000-00000000c001",
    created_at: "2026-11-19T08:00:00Z",
    last_seen_at: "2026-11-19T09:00:00Z",
    user_agent: "Firefox",
    current: true,
  },
  {
    id: "0190a000-0000-7000-8000-00000000c002",
    created_at: "2026-11-18T08:00:00Z",
    last_seen_at: "2026-11-18T09:00:00Z",
    user_agent: "Chrome",
    current: false,
  },
];

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("style");
});

describe("user tab", () => {
  it("saves a preference, applies it at once, and says it follows the user", async () => {
    let saved: Record<string, unknown> = {};
    let me = { ...ADMIN, preferences: PREFS };
    const api = fakeApi({
      "GET /auth/me": () => [200, me],
      "GET /me/preferences": () => [200, { ...PREFS, ...saved }],
      "PATCH /me/preferences": (body) => {
        saved = { ...saved, ...(body as Record<string, unknown>) };
        me = { ...me, preferences: { ...PREFS, ...saved } };
        return [200, { ...PREFS, ...saved }];
      },
      "GET /me/sessions": [200, SESSIONS],
      "GET /views": [200, []],
    });
    renderAt("/me");
    await screen.findByRole("heading", { level: 1, name: "User" });
    await userEvent.selectOptions(
      await screen.findByLabelText("Text size"),
      "150",
    );
    await waitFor(() => {
      expect(
        document.documentElement.style.getPropertyValue("--font-scale"),
      ).toBe("1.5");
    });
    expect(
      api.calls.find((c) => c.key === "PATCH /me/preferences")?.body,
    ).toEqual({ font_scale: 150 });
    expect(await screen.findByText(/applies on every device/)).toHaveAttribute(
      "role",
      "status",
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Theme"),
      "high-contrast",
    );
    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe("high-contrast");
    });
  });

  it("lists sessions and signs out another one, never the current one", async () => {
    const api = fakeApi({
      "GET /auth/me": [200, { ...ADMIN, preferences: PREFS }],
      "GET /me/preferences": [200, PREFS],
      "GET /me/sessions": [200, SESSIONS],
      "GET /views": [200, []],
      [`DELETE /me/sessions/${SESSIONS[1]?.id ?? ""}`]: [204, undefined],
    });
    renderAt("/me");
    const table = await screen.findByRole("table", {
      name: /Where you are signed in/,
    });
    await within(table).findByText("This session");
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("This session");
    expect(within(rows[1] as HTMLElement).queryByRole("button")).toBeNull();
    await userEvent.click(
      within(rows[2] as HTMLElement).getByRole("button", {
        name: "Sign out this session",
      }),
    );
    await waitFor(() => {
      expect(
        api.calls.some((c) => c.key.startsWith("DELETE /me/sessions/")),
      ).toBe(true);
    });
  });

  it("shows a refusal from the API", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, preferences: PREFS }],
      "GET /me/preferences": [200, PREFS],
      "PATCH /me/preferences": [400, problem(400, "at most 240 minutes")],
      "GET /me/sessions": [200, SESSIONS],
      "GET /views": [200, []],
    });
    renderAt("/me");
    await userEvent.selectOptions(
      await screen.findByLabelText("Sign out after inactivity"),
      "480",
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
