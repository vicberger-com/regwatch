import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, fakeApi, problem } from "@/test/api";
import { renderAt } from "@/test/render";

const ID = "0190a000-0000-7000-8000-0000000000f1";
const OFF = "0190a000-0000-7000-8000-0000000000f2";
const entry = {
  id: ID,
  key: "us-federal-register-it",
  name: "Federal Register",
  summary: "US federal rules and notices.",
  kind: "api_feed",
  url: "https://www.federalregister.gov/api/v1/documents.json",
  terms_url: "https://www.federalregister.gov/reader-aids/policy/legal-status",
  credibility: "official",
  language: "en",
  jurisdictions: ["US"],
  health: "unknown",
  available: true,
  captured: false,
  following: false,
};
const off = {
  ...entry,
  id: OFF,
  key: "gb-legislation-it",
  name: "legislation.gov.uk",
  jurisdictions: ["GB"],
  terms_url: "javascript:alert(1)",
  available: false,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(following: { now: boolean }, extra = {}) {
  return {
    "GET /auth/me": [200, ADMIN],
    "GET /me/sessions": [200, []],
    "GET /views": [200, []],
    "GET /catalogue": () => [
      200,
      [{ ...entry, following: following.now, captured: following.now }, off],
    ],
    ...extra,
  } as Parameters<typeof fakeApi>[0];
}

describe("feeds (M11.2)", () => {
  it("follows and unfollows a feed with its tick box", async () => {
    const state = { now: false };
    const api = fakeApi(
      routes(state, {
        [`PUT /catalogue/${ID}/follow`]: () => {
          state.now = true;
          return [204, undefined];
        },
        [`DELETE /catalogue/${ID}/follow`]: () => {
          state.now = false;
          return [204, undefined];
        },
      }),
    );
    renderAt("/me");
    const feeds = await screen.findByRole("region", { name: "Feeds" });
    const box = await within(feeds).findByRole("checkbox", {
      name: /Federal Register/,
    });
    expect(within(feeds).getByRole("group", { name: "US" })).toBeVisible();
    expect(
      within(feeds).getByText("Not captured until someone follows it"),
    ).toBeVisible();
    await userEvent.click(box);
    expect(await within(feeds).findByText("Being captured")).toBeVisible();
    expect(box).toBeChecked();
    await userEvent.click(box);
    await waitFor(() => {
      expect(box).not.toBeChecked();
    });
    expect(api.calls.map((c) => c.key)).toContain(
      `DELETE /catalogue/${ID}/follow`,
    );
  });

  it("shows a feed an administrator turned off, and only safe links", async () => {
    fakeApi(routes({ now: false }));
    renderAt("/me");
    const feeds = await screen.findByRole("region", { name: "Feeds" });
    const box = await within(feeds).findByRole("checkbox", {
      name: /legislation\.gov\.uk/,
    });
    expect(box).toBeDisabled();
    expect(
      within(feeds).getByText("Turned off by an administrator"),
    ).toBeVisible();
    expect(
      within(feeds).queryByRole("link", {
        name: "Terms of use for legislation.gov.uk",
      }),
    ).toBeNull();
    const terms = within(feeds).getByRole("link", {
      name: "Terms of use for Federal Register",
    });
    expect(terms).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("says why a follow was refused", async () => {
    fakeApi(
      routes(
        { now: false },
        {
          [`PUT /catalogue/${ID}/follow`]: [
            409,
            problem(409, "You can follow at most 200 sources."),
          ],
        },
      ),
    );
    renderAt("/me");
    const feeds = await screen.findByRole("region", { name: "Feeds" });
    await userEvent.click(
      await within(feeds).findByRole("checkbox", { name: /Federal Register/ }),
    );
    expect(await within(feeds).findByRole("alert")).toHaveTextContent(
      "at most 200",
    );
  });
});
