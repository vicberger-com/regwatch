import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

import { type Setting } from "./api";

const ME = { ...ADMIN, permissions: ["settings.manage"] };
const SETTINGS: Setting[] = [
  { key: "auth.lockout_minutes", type: "integer", value: 30, default: 30 },
  { key: "auth.breach_check_enabled", type: "boolean", value: false },
  {
    key: "map.projection",
    type: "enum",
    value: "equal-earth",
    values: ["equal-earth", "mercator"],
  },
  {
    key: "outputs.allowed_recipient_domains",
    type: "list",
    value: ["example.org"],
    note: "empty list blocks all email",
  },
  { key: "classification.min_confidence", type: "number", value: 0.6 },
  { key: "general.site_title", type: "string", value: "Regulatory Monitor" },
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("settings screen", () => {
  it("renders a control per type, grouped by prefix", async () => {
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/settings": [200, SETTINGS],
    });
    renderAt("/admin/settings");
    const auth = await screen.findByRole("group", { name: "auth" });
    const form = (name: string) => screen.getByRole("form", { name });
    expect(
      within(auth).getByRole("form", { name: "auth.breach_check_enabled" }),
    ).toContainElement(
      within(form("auth.breach_check_enabled")).getByRole("checkbox"),
    );
    expect(within(form("map.projection")).getByRole("combobox")).toHaveValue(
      "equal-earth",
    );
    expect(
      within(form("outputs.allowed_recipient_domains")).getByRole("textbox"),
    ).toHaveValue("example.org");
    expect(screen.getByText(/empty list blocks all email/)).toBeInTheDocument();
  });

  it("checks the type before saving, then saves", async () => {
    const sent: unknown[] = [];
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/settings": [200, SETTINGS],
    });
    const fake = globalThis.fetch;
    vi.stubGlobal("fetch", async (request: Request) => {
      if (request.method === "PUT") {
        const body = (await request.json()) as { value: unknown };
        sent.push(body.value);
        const out = { ...SETTINGS[0], value: body.value };
        return new Response(JSON.stringify(out), {
          headers: { "Content-Type": "application/json" },
        });
      }
      return fake(request);
    });
    renderAt("/admin/settings");
    const user = userEvent.setup();
    const form = await screen.findByRole("form", {
      name: "auth.lockout_minutes",
    });
    const input = within(form).getByRole("textbox");
    const save = within(form).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await user.clear(input);
    await user.type(input, "ten");
    await user.click(save);
    expect(within(form).getByRole("alert")).toHaveTextContent(
      "Enter a whole number.",
    );
    expect(sent).toEqual([]);
    await user.clear(input);
    await user.type(input, "45");
    await user.click(save);
    expect(await within(form).findByText("Saved.")).toBeInTheDocument();
    expect(sent).toEqual([45]);
  });

  it("shows the server's reason when a value is refused", async () => {
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/settings": [200, SETTINGS],
      "PUT /admin/settings/auth.lockout_minutes": [
        400,
        problem(400, "value: must be between 1 and 1440"),
      ],
    });
    renderAt("/admin/settings");
    const user = userEvent.setup();
    const form = await screen.findByRole("form", {
      name: "auth.lockout_minutes",
    });
    await user.clear(within(form).getByRole("textbox"));
    await user.type(within(form).getByRole("textbox"), "5000");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "must be between 1 and 1440",
    );
  });

  it("is closed without settings.manage", async () => {
    fakeApi({ "GET /auth/me": [200, { ...ADMIN, permissions: [] }] });
    renderAt("/admin/settings");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
  });

  it("reports a failed load", async () => {
    fakeApi({
      "GET /auth/me": [200, ME],
      "GET /admin/settings": [500, problem(500, "Boom")],
    });
    renderAt("/admin/settings");
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });
});
