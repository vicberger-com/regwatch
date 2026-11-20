import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

import { TOPICS } from "./topics";

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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("help tips", () => {
  it("open on click or focus with a tip and a link to the help page, and close with Escape", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /me/preferences": [200, PREFS],
      "GET /me/sessions": [200, []],
      "GET /views": [200, []],
    });
    renderAt("/me");
    const button = await screen.findByRole("button", {
      name: "About Text size",
    });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const tip = document.getElementById(
      button.getAttribute("aria-controls") ?? "",
    );
    expect(tip).toHaveTextContent("Makes all text larger");
    expect(tip).toHaveAttribute("aria-live", "polite");
    const link = within(tip as HTMLElement).getByRole("link", {
      name: "Learn more about Text size",
    });
    expect(link).toHaveAttribute("href", "/help#me-font-scale");
    await userEvent.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    // Keyboard: Tab onto the next tip opens it.
    act(() => {
      screen.getByRole("button", { name: "About Theme" }).focus();
    });
    expect(screen.getByRole("button", { name: "About Theme" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("has a help section for every topic, and the link lands on it with focus", async () => {
    fakeApi({ "GET /auth/me": [200, ADMIN] });
    renderAt("/help#me-font-scale");
    const heading = await screen.findByRole("heading", {
      level: 3,
      name: "Text size",
    });
    await waitFor(() => {
      expect(heading).toHaveFocus();
    });
    for (const t of TOPICS)
      expect(document.getElementById(t.id)).not.toBeNull();
    expect(new Set(TOPICS.map((t) => t.id)).size).toBe(TOPICS.length); // ids are unique
  });
});
