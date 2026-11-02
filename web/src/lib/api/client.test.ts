import { describe, expect, it, vi } from "vitest";

import { API_BASE_URL, createApiClient, isProblem } from "./client";

function jsonResponse(body: unknown, status: number, type: string): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": type },
  });
}

describe("api client", () => {
  it("calls contract paths under /api/v1 with the session cookie", async () => {
    const fetch = vi.fn((request: Request) => {
      expect(request.url).toBe(`http://localhost${API_BASE_URL}/version`);
      expect(request.credentials).toBe("same-origin");
      return Promise.resolve(
        jsonResponse(
          { version: "0.1.0", commit: "abc" },
          200,
          "application/json",
        ),
      );
    });
    const client = createApiClient({
      baseUrl: `http://localhost${API_BASE_URL}`,
      fetch,
    });
    const { data, error } = await client.GET("/version");
    expect(error).toBeUndefined();
    expect(data?.version).toBe("0.1.0");
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("returns problem details from a stub as the error", async () => {
    const problem = {
      type: "https://regwatch/errors/not-implemented",
      title: "Not Implemented",
      status: 501,
    };
    const fetch = vi.fn(() =>
      Promise.resolve(jsonResponse(problem, 501, "application/problem+json")),
    );
    const client = createApiClient({
      baseUrl: "http://localhost/api/v1",
      fetch,
    });
    const { data, error, response } = await client.GET("/admin/users/{id}", {
      params: { path: { id: "00000000-0000-4000-8000-000000000000" } },
    });
    expect(data).toBeUndefined();
    expect(response.status).toBe(501);
    expect(isProblem(error)).toBe(true);
  });

  it("recognises problem details only by their required members", () => {
    expect(isProblem({ type: "t", title: "x", status: 404 })).toBe(true);
    expect(isProblem({ type: "t", title: "x" })).toBe(false);
    expect(isProblem(null)).toBe(false);
    expect(isProblem("error")).toBe(false);
  });
});
