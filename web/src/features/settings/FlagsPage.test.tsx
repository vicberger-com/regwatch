import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

const ME = { ...ADMIN, permissions: ["settings.manage"] };
const FLAGS = [
  {
    key: "search.internet",
    enabled: false,
    description: "Enable the search-query connector",
  },
  {
    key: "translation.enabled",
    enabled: false,
    description: "Run the translation step",
  },
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("feature flags screen", () => {
  it("turns a flag on", async () => {
    let flags = FLAGS;
    const api = fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/feature-flags": () => [200, flags],
      "PATCH /admin/feature-flags/search.internet": () => {
        flags = FLAGS.map((f) =>
          f.key === "search.internet" ? { ...f, enabled: true } : f,
        );
        return [200, flags.find((f) => f.key === "search.internet")];
      },
    });
    renderAt("/admin/flags");
    const toggle = await screen.findByRole("switch", {
      name: "search.internet",
    });
    expect(toggle).toHaveAccessibleDescription(
      "Enable the search-query connector",
    );
    await userEvent.setup().click(toggle);
    await vi.waitFor(() => {
      expect(
        screen.getByRole("switch", { name: "search.internet" }),
      ).toBeChecked();
    });
    expect(api.calls.find((c) => c.key.startsWith("PATCH"))?.body).toEqual({
      enabled: true,
    });
  });

  it("shows the precondition when the API refuses", async () => {
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/feature-flags": [200, FLAGS],
      "PATCH /admin/feature-flags/translation.enabled": [
        409,
        problem(409, "Record translation.data_processing_basis first (8.4)."),
      ],
    });
    renderAt("/admin/flags");
    await userEvent
      .setup()
      .click(
        await screen.findByRole("switch", { name: "translation.enabled" }),
      );
    await vi.waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "data_processing_basis",
      );
    });
    expect(
      screen.getByRole("switch", { name: "translation.enabled" }),
    ).not.toBeChecked();
  });

  it("is closed without settings.manage", async () => {
    fakeApi({ "GET /auth/me": [200, { ...ADMIN, permissions: [] }] });
    renderAt("/admin/flags");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
  });

  it("reports a failed load", async () => {
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/feature-flags": [500, problem(500, "Boom")],
    });
    renderAt("/admin/flags");
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });
});
