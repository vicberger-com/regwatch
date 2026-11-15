import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { problemText } from "@/lib/auth/session";

import {
  facetsQuery,
  flatten,
  useCreateFacet,
  useCreateTerm,
  type Facet,
  type Term,
} from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

/** `/admin/taxonomy` (screens.md): facets and their term trees; create forms for managers. */
export function TaxonomyPage({ canManage }: { canManage: boolean }) {
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
          {canManage && <CreateFacet />}
        </nav>
        {current && <FacetDetail facet={current} canManage={canManage} />}
      </div>
    </section>
  );
}

function FacetDetail({
  facet,
  canManage,
}: {
  facet: Facet;
  canManage: boolean;
}) {
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
      {canManage && facet.value_type === "term" && <CreateTerm facet={facet} />}
    </div>
  );
}

// Deeper levels are not drawn, so a very deep hierarchy cannot freeze the page
// (web review finding 9; BL-76 for a depth cap in the API).
const MAX_DEPTH = 16;

function TermTree({
  terms,
  label,
  depth = 0,
}: {
  terms: Term[];
  label?: string;
  depth?: number;
}) {
  if (depth >= MAX_DEPTH) {
    return (
      <p className="ml-4 text-text-muted">Deeper terms are not shown here.</p>
    );
  }
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
            <TermTree terms={t.children} depth={depth + 1} />
          )}
        </li>
      ))}
    </ul>
  );
}

function CreateFacet() {
  const create = useCreateFacet();
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [inSelector, setInSelector] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      { key, label, value_type: "term", show_in_view_selector: inSelector },
      {
        onSuccess: () => {
          setKey("");
          setLabel("");
          setInSelector(false);
        },
      },
    );
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label="Create facet"
      className="mt-4 flex flex-col gap-2 rounded border border-border bg-surface p-3"
    >
      <h2 className="font-semibold">Create facet</h2>
      <label className="flex flex-col gap-1">
        <span>Key (lower case, digits, _)</span>
        <input
          value={key}
          onChange={(e) => {
            setKey(e.target.value);
          }}
          className={field}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span>Label</span>
        <input
          value={label}
          onChange={(e) => {
            setLabel(e.target.value);
          }}
          className={field}
        />
      </label>
      <label className="flex items-center gap-1">
        <input
          type="checkbox"
          checked={inSelector}
          onChange={(e) => {
            setInSelector(e.target.checked);
          }}
        />
        Show in the view selector
      </label>
      <p role="alert" className="text-critical">
        {problemText(create.error, "The facet could not be created.")}
      </p>
      <button
        type="submit"
        className={button}
        disabled={create.isPending || !key || !label.trim()}
      >
        Create facet
      </button>
    </form>
  );
}

function CreateTerm({ facet }: { facet: Facet }) {
  const create = useCreateTerm();
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [parent, setParent] = useState("");
  const [synonyms, setSynonyms] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const list = synonyms
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    create.mutate(
      {
        facet: facet.key,
        body: {
          key,
          label,
          parent_id: parent || null,
          ...(list.length ? { synonyms: list } : {}),
        },
      },
      {
        onSuccess: () => {
          setKey("");
          setLabel("");
          setParent("");
          setSynonyms("");
        },
      },
    );
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label={`Add term to ${facet.label}`}
      className="flex flex-col gap-2 rounded border border-border bg-surface p-3"
    >
      <h3 className="font-semibold">Add term</h3>
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1">
          <span>Key</span>
          <input
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
            }}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Label</span>
          <input
            value={label}
            onChange={(e) => {
              setLabel(e.target.value);
            }}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Parent</span>
          <select
            value={parent}
            onChange={(e) => {
              setParent(e.target.value);
            }}
            className={field}
          >
            <option value="">(top level)</option>
            {flatten(facet.terms ?? []).map(({ term, depth }) => (
              <option key={term.id} value={term.id}>
                {"  ".repeat(depth)}
                {term.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="flex flex-col gap-1">
        <span>Synonyms (comma-separated)</span>
        <input
          value={synonyms}
          onChange={(e) => {
            setSynonyms(e.target.value);
          }}
          className={field}
        />
      </label>
      <p role="alert" className="text-critical">
        {problemText(create.error, "The term could not be created.")}
      </p>
      <button
        type="submit"
        className={button}
        disabled={create.isPending || !key || !label.trim()}
      >
        Add term
      </button>
    </form>
  );
}
