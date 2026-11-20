import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi } from "@/test/api";
import { renderAt } from "@/test/render";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("browser printing (M8.5)", () => {
  it("prints the page from the header, leaving the frame but not the markings off paper", async () => {
    const print = vi.fn();
    vi.stubGlobal("print", print);
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "GET /branding": [
        200,
        { site_title: "regwatch", required_markings: "INTERNAL USE" },
      ],
      "GET /version": [200, { version: "0.1.0", commit: "abc" }],
    });
    renderAt("/help");
    await userEvent.click(await screen.findByRole("button", { name: "Print" }));
    expect(print).toHaveBeenCalledOnce();
    // The print stylesheet keys on these (index.css; Tailwind's print variant).
    expect(screen.getByRole("banner")).toHaveClass("print:hidden");
    expect(
      screen
        .getByRole("navigation", { name: "Main" })
        .closest(".print\\:hidden"),
    ).not.toBeNull();
    expect(
      screen.getByRole("contentinfo").closest(".print\\:hidden"),
    ).toBeNull();
    expect(screen.getByRole("main").closest(".print\\:hidden")).toBeNull();
  });
});
