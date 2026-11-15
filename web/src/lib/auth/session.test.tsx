/** Session hygiene in the browser (web review findings 1 to 3). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";
import { ADMIN, fakeApi, problem } from "@/test/api";

function renderWith(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { queryClient, router };
}

const page = (items: unknown[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 200,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sign-out", () => {
  it("keeps the user signed in, and says so, when the API refuses it", async () => {
    fakeApi({
      "GET /auth/me": [200, ADMIN],
      "POST /auth/logout": [403, problem(403)],
    });
    renderWith("/");
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "still signed in",
    );
    expect(screen.getByText(/Signed in as Ada Admin/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });

  it("treats an already expired session as signed out", async () => {
    let me: unknown = ADMIN;
    fakeApi({
      "GET /auth/me": () => (me ? [200, me] : [401, problem(401)]),
      "POST /auth/logout": () => {
        me = null;
        return [401, problem(401)];
      },
    });
    renderWith("/");
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Sign out" }));
    await screen.findByRole("heading", { name: "Sign in" });
  });

  it("leaves no password or temporary password in the caches", async () => {
    let me: unknown = null;
    fakeApi({
      "GET /auth/me": () => (me ? [200, me] : [401, problem(401)]),
      "POST /auth/login": () => {
        me = ADMIN;
        return [200, ADMIN];
      },
      "POST /auth/logout": () => {
        me = null;
        return [204, undefined];
      },
    });
    const { queryClient } = renderWith("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "admin@example.org");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    await screen.findByRole("heading", { name: "Sign in" });
    const cached = JSON.stringify([
      queryClient
        .getMutationCache()
        .getAll()
        .map((m) => m.state),
      queryClient
        .getQueryCache()
        .getAll()
        .map((q) => q.state.data),
    ]);
    expect(cached).not.toContain("correct horse battery");
  });
});

describe("sign-in", () => {
  it("never shows a previous user's cached data to the next user", async () => {
    let me: unknown = ADMIN;
    fakeApi({
      "GET /auth/me": () => [200, me],
      "GET /admin/users": () =>
        me === ADMIN
          ? [200, page([{ ...ADMIN, email: "secret-a@example.org" }])]
          : [403, problem(403)],
      "POST /auth/login": () => {
        me = { ...ADMIN, id: "b", display_name: "Bea", email: "b@example.org" };
        return [200, me];
      },
    });
    const { router } = renderWith("/admin/users");
    expect(await screen.findByText("secret-a@example.org")).toBeInTheDocument();
    await router.navigate({ to: "/login", search: {} });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "b@example.org");
    await user.type(screen.getByLabelText("Password"), "b password here");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText(/Signed in as Bea/);
    await router.navigate({ to: "/admin/users" });
    await screen.findByRole("heading", { name: "Users" });
    expect(screen.queryByText("secret-a@example.org")).toBeNull();
  });
});
