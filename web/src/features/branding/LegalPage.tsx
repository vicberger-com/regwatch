import { useQuery } from "@tanstack/react-query";

import { problemText } from "@/lib/auth/session";

import { legalQuery } from "./api";
import { LegalHtml } from "./BrandingPage";

/** `/legal` (screens.md, CP-08): the rendered legal page and the required markings, public. */
export function LegalPage() {
  const legal = useQuery(legalQuery);
  return (
    <section
      aria-labelledby="legal-heading"
      className="flex max-w-3xl flex-col gap-4"
    >
      <h1 id="legal-heading" className="text-2xl font-semibold">
        Legal
      </h1>
      {legal.isPending ? (
        <p>Loading the legal page…</p>
      ) : legal.isError ? (
        <p role="alert" className="text-critical">
          {problemText(legal.error, "The legal page could not be loaded.")}
        </p>
      ) : (
        <>
          <LegalHtml html={legal.data.html ?? ""} />
          {legal.data.required_markings && (
            <p className="text-text-muted">{legal.data.required_markings}</p>
          )}
        </>
      )}
    </section>
  );
}
