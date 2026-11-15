import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem, type Routes } from "@/test/api";
import { renderAt } from "@/test/render";

const BRANDING = {
  site_title: "Policy Watch",
  logo_url: "/api/v1/branding/logo?v=abc123def456",
  primary_color: "#123ABC",
  required_markings: "INTERNAL USE",
};
const BASE = {
  "GET /auth/me": [200, ADMIN],
  "GET /branding": [200, BRANDING],
  "GET /version": [200, { version: "0.1.0", commit: "abc" }],
  "GET /legal": [
    200,
    { html: "<h2>Terms</h2><p>Text</p>", required_markings: "INTERNAL USE" },
  ],
} satisfies Routes;

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.style.removeProperty("--brand-accent");
});

describe("branding in the shell", () => {
  it("shows the logo, title, colour and footer", async () => {
    fakeApi(BASE);
    renderAt("/legal");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(await within(nav).findByText("Policy Watch")).toBeInTheDocument();
    expect(nav.querySelector("img")).toHaveAttribute("src", BRANDING.logo_url);
    expect(document.title).toBe("Policy Watch");
    expect(
      document.documentElement.style.getPropertyValue("--brand-accent"),
    ).toBe("#123ABC");
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByRole("link", { name: "Legal" })).toHaveAttribute(
      "href",
      "/legal",
    );
    expect(
      await within(footer).findByText("Version 0.1.0"),
    ).toBeInTheDocument();
    expect(within(footer).getByText("INTERNAL USE")).toBeInTheDocument();
  });

  it("ignores a colour that is not a hex value and falls back to the default title", async () => {
    document.documentElement.style.setProperty("--brand-accent", "#000000");
    fakeApi({
      ...BASE,
      "GET /branding": [
        200,
        { site_title: "", primary_color: "red;background:url(x)" },
      ],
    });
    renderAt("/legal");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    await vi.waitFor(() => {
      expect(
        document.documentElement.style.getPropertyValue("--brand-accent"),
      ).toBe("");
    });
    expect(within(nav).getByText("regwatch")).toBeInTheDocument();
    expect(nav.querySelector("img")).toBeNull();
  });

  it("renders the legal page from the API", async () => {
    fakeApi(BASE);
    renderAt("/legal");
    expect(
      await screen.findByRole("heading", { name: "Terms" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "Legal" }),
    ).toBeInTheDocument();
  });

  it("reports a failed legal page", async () => {
    fakeApi({ ...BASE, "GET /legal": [500, problem(500, "Boom")] });
    renderAt("/legal");
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });

  it("shows the public logo on the sign-in page and hides it when there is none", async () => {
    fakeApi({ "GET /auth/me": [401, problem(401)] });
    renderAt("/login");
    await screen.findByRole("heading", { name: "Sign in" });
    const logo = document.querySelector('img[src="/api/v1/branding/logo"]');
    expect(logo).not.toBeNull();
    if (logo) fireEvent.error(logo);
    expect(
      document.querySelector('img[src="/api/v1/branding/logo"]'),
    ).toBeNull();
  });
});
