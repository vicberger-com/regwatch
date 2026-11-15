/** Branding and logo (#32, BL-68). */
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

function useBrandingMutation<T, R>(call: (input: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: () => client.invalidateQueries({ queryKey: ["branding"] }),
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
