import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

const OWNER = { ...ADMIN, permissions: ["settings.manage", "items.read"] };
const PRINTER = {
  id: "p1",
  name: "Floor 2",
  ipp_url: "ipps://printer.example.internal:631/ipp/print",
  default_media: "iso_a4_210x297mm",
  enabled: true,
  tls_sha256: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("printers (M8.5b)", () => {
  it("lists printers, adds one, shows the server's refusal and queues a test page", async () => {
    let tries = 0;
    const api = fakeApi({
      "GET /auth/me": [200, OWNER],
      "GET /admin/printers": [200, [PRINTER]],
      "POST /admin/printers": (body) => {
        tries += 1;
        return tries === 1
          ? [
              422,
              {
                ...problem(422),
                errors: [
                  {
                    field: "ipp_url",
                    message:
                      "the printer's address is outside the allowed printer networks",
                  },
                ],
              },
            ]
          : [201, { ...PRINTER, id: "p2", ...(body as object) }];
      },
      "POST /admin/printers/p1/test-page": [
        202,
        {
          id: "j1",
          kind: "print",
          status: "queued",
          created_at: "2026-11-21T00:00:00Z",
        },
      ],
    });
    renderAt("/admin/printers");
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Floor 2")).toBeVisible();
    expect(within(table).getByText("Verified")).toBeVisible();
    const form = screen.getByRole("form", { name: "Add a printer" });
    await userEvent.type(
      within(form).getByRole("textbox", { name: "Name" }),
      "Lobby",
    );
    await userEvent.type(
      within(form).getByRole("textbox", { name: "Address" }),
      "ipps://8.8.8.8/ipp/print",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "outside the allowed printer networks",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    await waitFor(() => {
      expect(
        api.calls.filter((c) => c.key === "POST /admin/printers"),
      ).toHaveLength(2);
    });
    expect(
      api.calls.filter((c) => c.key === "POST /admin/printers").at(-1)?.body,
    ).toEqual({
      name: "Lobby",
      ipp_url: "ipps://8.8.8.8/ipp/print",
    });
    await userEvent.click(
      within(table).getByRole("button", {
        name: "Print a test page on Floor 2",
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Test page queued",
    );
  });
});
