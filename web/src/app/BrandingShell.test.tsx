import { screen, within } from "@testing-library/react";
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
  "GET /branding/public": [
    200,
    {
      site_title: "Policy Watch",
      logo_url: "/api/v1/branding/logo?v=abc123def456",
      primary_color: "#123ABC",
      has_legal_page: true,
    },
  ],
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
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(await within(nav).findByText("Policy Watch")).toBeInTheDocument();
    expect(nav.querySelector("img")).toHaveAttribute("src", BRANDING.logo_url);
    expect(document.title).toBe("Home · Policy Watch"); // screen, then site title (U-M0-4)
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
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    await vi.waitFor(() => {
      expect(
        document.documentElement.style.getPropertyValue("--brand-accent"),
      ).toBe("");
    });
    expect(within(nav).getByText("regwatch")).toBeInTheDocument();
    expect(nav.querySelector("img")).toBeNull();
  });

  it("renders the legal page publicly, outside the shell (CP-08)", async () => {
    fakeApi({ ...BASE, "GET /auth/me": [401, problem(401)] });
    renderAt("/legal");
    expect(
      await screen.findByRole("heading", { name: "Terms" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "Legal" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
    expect(
      screen.getByRole("link", { name: "Back to Policy Watch" }),
    ).toHaveAttribute("href", "/");
    expect(document.title).toBe("Legal · Policy Watch");
  });

  it("reports a failed legal page", async () => {
    fakeApi({ ...BASE, "GET /legal": [500, problem(500, "Boom")] });
    renderAt("/legal");
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });

  it("shows the sign-in page with the public branding and a legal link (CP-08)", async () => {
    fakeApi({ ...BASE, "GET /auth/me": [401, problem(401)] });
    renderAt("/login");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(screen.getByRole("main")).toBeInTheDocument(); // U-M0-8
    expect(await screen.findByText("Policy Watch")).toBeInTheDocument();
    await vi.waitFor(() => {
      expect(document.title).toBe("Sign in · Policy Watch");
    });
    expect(document.querySelector("header img")).toHaveAttribute(
      "src",
      "/api/v1/branding/logo?v=abc123def456",
    );
    expect(screen.getByRole("link", { name: "Legal" })).toHaveAttribute(
      "href",
      "/legal",
    );
    expect(
      document.documentElement.style.getPropertyValue("--brand-accent"),
    ).toBe("#123ABC");
  });

  it("signs in without branding when the summary is unavailable", async () => {
    fakeApi({
      "GET /auth/me": [401, problem(401)],
      "GET /branding/public": [500, problem(500)],
    });
    renderAt("/login");
    await screen.findByRole("heading", { name: "Sign in" });
    await vi.waitFor(() => {
      expect(document.title).toBe("Sign in · regwatch");
    });
    expect(document.querySelector("header img")).toBeNull();
    expect(screen.queryByRole("link", { name: "Legal" })).toBeNull();
  });
});
