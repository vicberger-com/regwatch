/** Branding, logo and legal page (#32, BL-68). */
import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure } from "@/lib/auth/session";

export type Branding = Schemas["Branding"];
export type BrandingWrite = Schemas["BrandingWrite"];

/** The API refuses a larger logo; checked first so the user hears why at once. */
export const MAX_LOGO_BYTES = 1024 * 1024;
export const COLOR = /^#[0-9A-Fa-f]{6}$/;

export const brandingQuery = queryOptions({
  queryKey: ["branding"],
  queryFn: async (): Promise<Branding> => {
    const result = await api.GET("/branding");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
  staleTime: 5 * 60_000,
});

export const legalQuery = queryOptions({
  queryKey: ["branding", "legal"],
  queryFn: async () => {
    // Revalidate: the public 60 s cache must not show the editor an old page (review R4).
    const result = await api.GET("/legal", { cache: "no-cache" });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

function useBrandingMutation<T, R>(call: (input: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ["branding"] }),
        client.invalidateQueries({ queryKey: ["admin", "settings"] }),
      ]),
  });
}

export function useSaveBranding() {
  return useBrandingMutation(async (body: BrandingWrite) => {
    const result = await api.PUT("/admin/branding", { body });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  });
}

export function useUploadLogo() {
  return useBrandingMutation(async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const result = await api.POST("/admin/branding/logo", {
      // openapi-fetch sends FormData as-is; the browser sets the multipart boundary.
      body: form as unknown as { file?: string },
    });
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  });
}

export function useSaveLegal() {
  return useBrandingMutation(
    async (body: { page_markdown: string; required_markings: string }) => {
      const result = await api.PUT("/admin/legal", { body });
      if (!result.response.ok) throw failure(result);
    },
  );
}

export type BrandingPublic = Schemas["BrandingPublic"];

/** What the sign-in and legal pages may show before sign-in (CP-08). */
export const publicBrandingQuery = queryOptions({
  queryKey: ["branding", "public"],
  queryFn: async (): Promise<BrandingPublic | null> => {
    const result = await api.GET("/branding/public");
    return result.response.ok ? (result.data ?? null) : null; // the page works without it
  },
  staleTime: 5 * 60_000,
});
