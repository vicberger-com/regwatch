import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem, type Routes } from "@/test/api";
import { renderAt } from "@/test/render";

const ME = { ...ADMIN, permissions: ["settings.manage"] };
const BRANDING = {
  site_title: "Regulatory Monitor",
  company_name: "Example Ltd",
  company_short_name: "Example",
  company_address: "1 Street\nTown",
  primary_color: null,
  logo_url: null,
  required_markings: "INTERNAL",
};
const BASE = {
  "GET /auth/me": [200, ME],
  "GET /branding": [200, BRANDING],
} satisfies Routes;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("branding screen", () => {
  it("is closed without settings.manage", async () => {
    fakeApi({ ...BASE, "GET /auth/me": [200, { ...ADMIN, permissions: [] }] });
    renderAt("/admin/branding");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
  });

  it("saves title, company fields and colour, checking the colour first", async () => {
    const api = fakeApi({ ...BASE, "PUT /admin/branding": [200, BRANDING] });
    renderAt("/admin/branding");
    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: "Branding" });
    expect(within(form).getByLabelText("Company address")).toHaveValue(
      "1 Street\nTown",
    );
    const color = within(form).getByLabelText(/Primary colour/);
    await user.type(color, "red");
    await user.click(
      within(form).getByRole("button", { name: "Save branding" }),
    );
    expect(within(form).getByRole("alert")).toHaveTextContent("hex value");
    expect(api.calls.some((c) => c.key === "PUT /admin/branding")).toBe(false);
    await user.clear(color);
    await user.type(color, "#123ABC");
    await user.clear(within(form).getByLabelText("Site title"));
    await user.type(within(form).getByLabelText("Site title"), "Policy Watch");
    await user.click(
      within(form).getByRole("button", { name: "Save branding" }),
    );
    expect(
      await within(form).findByText("Branding saved."),
    ).toBeInTheDocument();
    expect(
      api.calls.find((c) => c.key === "PUT /admin/branding")?.body,
    ).toEqual({
      site_title: "Policy Watch",
      company_name: "Example Ltd",
      company_short_name: "Example",
      company_address: "1 Street\nTown",
      primary_color: "#123ABC",
    });
  });

  it("uploads a logo as multipart and shows the API's refusal", async () => {
    const sent: (string | null)[] = [];
    const append = vi.spyOn(FormData.prototype, "append");
    fakeApi(BASE);
    const fake = globalThis.fetch;
    vi.stubGlobal("fetch", async (request: Request) => {
      if (request.method !== "POST") return fake(request);
      // Reading a body that holds jsdom's File never finishes under Node's fetch, so the
      // test checks the header here and the form contents through FormData.append.
      sent.push(request.headers.get("Content-Type"));
      const body = problem(415, "SVG logos may not contain <script>.");
      return new Response(JSON.stringify(body), {
        status: 415,
        headers: { "Content-Type": "application/problem+json" },
      });
    });
    renderAt("/admin/branding");
    const user = userEvent.setup();
    const input = await screen.findByLabelText(/Upload a PNG or SVG/);
    const big = new File(["x"], "big.png", { type: "image/png" });
    Object.defineProperty(big, "size", { value: 2 * 1024 * 1024 });
    await user.upload(input, big);
    expect(screen.getByText("The logo is larger than 1 MB.")).toHaveAttribute(
      "role",
      "alert",
    );
    expect(sent).toEqual([]);
    await user.upload(
      input,
      new File(["<svg/>"], "logo.svg", { type: "image/svg+xml" }),
    );
    expect(await screen.findByText(/may not contain <script>/)).toHaveAttribute(
      "role",
      "alert",
    );
    expect(sent[0]).toMatch(/^multipart\/form-data; boundary=/);
    const [name, value] = append.mock.calls[0] ?? [];
    expect(name).toBe("file");
    expect(value).toBeInstanceOf(File);
    append.mockRestore();
  });

  it("shows the current logo", async () => {
    fakeApi({
      ...BASE,
      "GET /branding": [
        200,
        { ...BRANDING, logo_url: "/api/v1/branding/logo?v=abc" },
      ],
    });
    renderAt("/admin/branding");
    expect(
      await screen.findByRole("img", { name: "Current logo" }),
    ).toHaveAttribute("src", "/api/v1/branding/logo?v=abc");
  });

  it("reports a failed load", async () => {
    fakeApi({ ...BASE, "GET /branding": [500, problem(500, "Boom")] });
    renderAt("/admin/branding");
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });
});
