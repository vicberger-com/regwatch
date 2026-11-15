import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { problemText } from "@/lib/auth/session";

import { facetsQuery, type Facet, type Term } from "./api";

const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

/** `/admin/taxonomy` (screens.md): facets and their term trees (read-only so far). */
export function TaxonomyPage() {
  const facets = useQuery(facetsQuery);
  const [selected, setSelected] = useState<string | null>(null);

  if (facets.isPending) return <p>Loading taxonomy…</p>;
  if (facets.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(facets.error, "The taxonomy could not be loaded.")}
      </p>
    );
  }
  const current = facets.data.find((f) => f.key === selected) ?? facets.data[0];

  return (
    <section aria-labelledby="taxonomy-heading" className="flex flex-col gap-4">
      <h1 id="taxonomy-heading" className="text-2xl font-semibold">
        Taxonomy
      </h1>
      <div className="flex flex-wrap gap-6">
        <nav aria-label="Facets" className="min-w-48">
          <ul className="flex flex-col gap-1">
            {facets.data.map((f) => (
              <li key={f.key}>
                <button
                  type="button"
                  aria-current={f.key === current?.key ? "true" : undefined}
                  className={`${button} w-full text-left ${f.key === current?.key ? "border-accent" : ""}`}
                  onClick={() => {
                    setSelected(f.key);
                  }}
                >
                  {f.label}
                  {f.system ? " (system)" : ""}
                  {f.hidden ? " (hidden)" : ""}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        {current && <FacetDetail facet={current} />}
      </div>
    </section>
  );
}

function FacetDetail({ facet }: { facet: Facet }) {
  const terms = facet.terms ?? [];
  return (
    <div className="flex min-w-72 flex-1 flex-col gap-3">
      <h2 className="text-lg font-semibold">{facet.label}</h2>
      <p className="text-text-muted">
        Key <code>{facet.key}</code> · {facet.value_type}
        {facet.multi ? " · multiple values" : ""}
        {facet.show_in_view_selector ? " · in the view selector" : ""}
      </p>
      {facet.value_type === "term" &&
        (terms.length > 0 ? (
          <TermTree terms={terms} label={`Terms of ${facet.label}`} />
        ) : (
          <p>No terms yet.</p>
        ))}
    </div>
  );
}

function TermTree({ terms, label }: { terms: Term[]; label?: string }) {
  return (
    <ul aria-label={label} className="ml-4 list-disc">
      {terms.map((t) => (
        <li key={t.id}>
          {t.label} <code className="text-text-muted">{t.key}</code>
          {t.synonyms && t.synonyms.length > 0 && (
            <span className="text-text-muted">
              {" "}
              · also {t.synonyms.join(", ")}
            </span>
          )}
          {t.children && t.children.length > 0 && (
            <TermTree terms={t.children} />
          )}
        </li>
      ))}
    </ul>
  );
}
