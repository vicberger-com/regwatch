import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "@/lib/api/client";
import { failure, problemText } from "@/lib/auth/session";

export type CatalogueEntry = Schemas["CatalogueEntry"];

export const catalogueQuery = {
  queryKey: ["catalogue"],
  queryFn: async (): Promise<CatalogueEntry[]> => {
    const result = await api.GET("/catalogue");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
};

/** A link the page may show: only http and https, never `javascript:`. */
function webLink(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}

function status(e: CatalogueEntry): string {
  if (!e.available) return "Turned off by an administrator";
  if (e.captured) return "Being captured";
  return "Not captured until someone follows it";
}

/**
 * The curated feed catalogue (M11.2, ADR-0012): a tick box per source follows it, and a
 * followed source is captured for everyone. Grouped by the places each source covers.
 */
export function FeedsEditor() {
  const client = useQueryClient();
  const catalogue = useQuery(catalogueQuery);
  const change = useMutation({
    mutationFn: async (args: { id: string; follow: boolean }) => {
      const path = { params: { path: { id: args.id } } };
      const result = args.follow
        ? await api.PUT("/catalogue/{id}/follow", path)
        : await api.DELETE("/catalogue/{id}/follow", path);
      if (!result.response.ok) throw failure(result);
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["catalogue"] }),
  });

  if (catalogue.isPending)
    return <p className="text-sm">Loading the catalogue…</p>;
  if (catalogue.isError)
    return (
      <p role="alert" className="text-sm">
        The catalogue could not be loaded.{" "}
        {problemText(catalogue.error, "Try again later.")}
      </p>
    );
  const groups = new Map<string, CatalogueEntry[]>();
  for (const e of catalogue.data) {
    const place = e.jurisdictions.join(", ") || "International";
    groups.set(place, [...(groups.get(place) ?? []), e]);
  }
  return (
    <div className="grid gap-3">
      <p className="text-sm text-text-muted">
        Tick a feed to follow it. One capture serves everyone who follows a
        feed. To add a feed that is not listed, ask an administrator.
      </p>
      {[...groups].map(([place, entries]) => (
        <fieldset key={place} className="rounded border border-border p-3">
          <legend className="px-1 text-sm font-semibold">{place}</legend>
          <ul className="grid gap-3">
            {entries.map((e) => {
              const terms = webLink(e.terms_url);
              return (
                <li key={e.id}>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1"
                      aria-describedby={`feed-${e.id}`}
                      checked={e.following}
                      // Unfollowing stays possible after an administrator turns it off.
                      disabled={
                        change.isPending || (!e.available && !e.following)
                      }
                      onChange={(ev) => {
                        change.mutate({ id: e.id, follow: ev.target.checked });
                      }}
                    />
                    <span className="font-medium">{e.name}</span>
                  </label>
                  <p
                    id={`feed-${e.id}`}
                    className="ml-6 text-sm text-text-muted"
                  >
                    {e.summary}
                    <span className="block">
                      {status(e)}
                      {e.health === "unhealthy" && " · failing at the moment"}
                    </span>
                  </p>
                  {terms && (
                    <a
                      href={terms}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-6 text-sm text-accent underline"
                    >
                      Terms of use for {e.name}
                    </a>
                  )}
                </li>
              );
            })}
          </ul>
        </fieldset>
      ))}
      {change.isError && (
        <p role="alert" className="text-sm">
          {problemText(change.error, "The change could not be saved.")}
        </p>
      )}
    </div>
  );
}
