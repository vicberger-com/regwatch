import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

const READER = { ...ADMIN, permissions: ["taxonomy.read"] };
const MANAGER = { ...ADMIN, permissions: ["taxonomy.read", "taxonomy.manage"] };
const YAML = "facets:\n  - key: topic\n    label: Topic\n";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function yamlFile(text: string, size?: number) {
  const file = new File([text], "taxonomy.yaml", { type: "application/yaml" });
  if (size !== undefined) Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("taxonomy import and export", () => {
  it("exports a YAML file; readers cannot import", async () => {
    fakeApi({
      "GET /auth/me": [200, READER],
      "GET /taxonomy/facets": [200, []],
    });
    const fake = globalThis.fetch;
    vi.stubGlobal("fetch", (request: Request) =>
      new URL(request.url).pathname.endsWith("/taxonomy/export")
        ? Promise.resolve(
            new Response(YAML, {
              headers: { "Content-Type": "application/yaml" },
            }),
          )
        : fake(request),
    );
    const create = vi.fn<(blob: Blob) => string>(() => "blob:taxonomy");
    const revoke = vi.fn();
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }),
    );
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    renderAt("/admin/taxonomy");
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Export YAML" }));
    await vi.waitFor(() => {
      expect(click).toHaveBeenCalled();
    });
    expect(await create.mock.calls[0]?.[0].text()).toBe(YAML);
    expect(revoke).toHaveBeenCalledWith("blob:taxonomy");
    expect(screen.queryByLabelText("Import YAML")).toBeNull();
  });

  it("imports a confirmed file as YAML and shows the summary", async () => {
    const sent: { type: string | null; body: string }[] = [];
    fakeApi({
      "GET /auth/me": [200, MANAGER],
      "GET /taxonomy/facets": [200, []],
    });
    const fake = globalThis.fetch;
    vi.stubGlobal("fetch", async (request: Request) => {
      if (request.method !== "POST") return fake(request);
      sent.push({
        type: request.headers.get("Content-Type"),
        body: await request.text(),
      });
      const summary = {
        facets_created: 1,
        facets_updated: 0,
        terms_created: 3,
        terms_updated: 2,
      };
      return new Response(JSON.stringify(summary), {
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderAt("/admin/taxonomy");
    const user = userEvent.setup();
    await user.upload(
      await screen.findByLabelText("Import YAML"),
      yamlFile(YAML),
    );
    expect(
      await screen.findByText(
        /1 facets added, 0 updated; 3 terms added, 2 updated/,
      ),
    ).toBeInTheDocument();
    expect(sent).toEqual([{ type: "application/yaml", body: YAML }]);
  });

  it("refuses an oversized file, does nothing when not confirmed, and shows a refusal", async () => {
    fakeApi({
      "GET /auth/me": [200, MANAGER],
      "GET /taxonomy/facets": [200, []],
      "POST /taxonomy/import": [
        400,
        problem(400, "facets: at most 200 facets"),
      ],
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderAt("/admin/taxonomy");
    const user = userEvent.setup();
    const input = await screen.findByLabelText("Import YAML");
    await user.upload(input, yamlFile(YAML, 3 * 1024 * 1024));
    expect(screen.getByText(/larger than 2 MB/)).toHaveAttribute(
      "role",
      "alert",
    );
    expect(confirm).not.toHaveBeenCalled();
    await user.upload(input, yamlFile(YAML));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/larger than 2 MB/)).toBeNull();
    confirm.mockReturnValue(true);
    await user.upload(input, yamlFile(YAML));
    expect(await screen.findByText(/at most 200 facets/)).toHaveAttribute(
      "role",
      "alert",
    );
  });

  it("reports a failed export", async () => {
    fakeApi({
      "GET /auth/me": [200, READER],
      "GET /taxonomy/facets": [200, []],
      "GET /taxonomy/export": [500, problem(500, "Boom")],
    });
    renderAt("/admin/taxonomy");
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Export YAML" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });
});
