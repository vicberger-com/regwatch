import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("left rail and settings home", () => {
  it("lists the rail commands with labels in their names, marking the current page", async () => {
    fakeApi({ "GET /auth/me": [200, ADMIN] });
    renderAt("/admin");
    const rail = await screen.findByRole("navigation", { name: "Main" });
    const settings = within(rail).getByRole("link", { name: "Settings" });
    expect(settings).toHaveAttribute("aria-current", "page");
    expect(within(rail).getByRole("link", { name: "Map" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(
      await screen.findByRole("heading", { level: 1, name: "Settings" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Users/ })).toHaveAttribute(
      "href",
      "/admin/users",
    );
  });

  it("pins the labels open and remembers it", async () => {
    fakeApi({ "GET /auth/me": [200, ADMIN] });
    renderAt("/admin");
    const pin = await screen.findByRole("button", { name: "Show labels" });
    expect(pin).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(pin);
    expect(pin).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem("regwatch.rail.pinned")).toBe("1");
  });

  it("shows only permitted areas, and no settings for users without an admin permission", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["sources.read"] }],
    });
    renderAt("/admin");
    await screen.findByRole("heading", { level: 1, name: "Settings" });
    expect(screen.getByRole("link", { name: /Sources/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Users/ })).toBeNull();
  });

  it("refuses the settings home without an admin permission", async () => {
    fakeApi({
      "GET /auth/me": [200, { ...ADMIN, permissions: ["items.read"] }],
    });
    renderAt("/admin");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).queryByRole("link", { name: "Settings" })).toBeNull();
  });
});
