import { useState } from "react";

import { problemText } from "@/lib/auth/session";

import { flatten, useDeleteTerm, useMergeTerm, type Term } from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

/** Merge a term into another of its facet, or delete it (the API deactivates a used term). */
export function TermActions({
  term,
  terms,
  onDone,
}: {
  term: Term;
  terms: Term[];
  onDone: (message: string) => void;
}) {
  const merge = useMergeTerm();
  const remove = useDeleteTerm();
  const [into, setInto] = useState("");
  // Neither the term itself nor anything below it can take its place.
  const below = new Set(flatten([term]).map(({ term: t }) => t.id));
  const targets = flatten(terms).filter(
    ({ term: t }) => t.active && !below.has(t.id),
  );
  const target = targets.find(({ term: t }) => t.id === into)?.term;
  const failed = merge.error ?? remove.error;

  function doMerge() {
    if (!target) return;
    if (
      !window.confirm(
        `Merge "${term.label}" into "${target.label}"? Items, sources and child terms move to "${target.label}", and "${term.label}" is deleted.`,
      )
    )
      return;
    merge.mutate(
      { id: term.id, into: target.id },
      {
        onSuccess: (r) => {
          onDone(
            `Merged into ${target.label}; ${String(r.items_moved ?? 0)} items re-tagged.`,
          );
        },
      },
    );
  }

  function doDelete() {
    if (
      !window.confirm(
        `Delete "${term.label}"? If items or sources use it, it is deactivated instead; child terms move up a level.`,
      )
    )
      return;
    remove.mutate(term.id, {
      onSuccess: () => {
        onDone(`${term.label} deleted, or deactivated if it is in use.`);
      },
    });
  }

  return (
    <div
      role="group"
      aria-label={`Merge or delete ${term.label}`}
      className="flex flex-wrap items-end gap-3 rounded border border-border p-3"
    >
      <label className="flex flex-col gap-1">
        <span>Merge into</span>
        <select
          value={into}
          onChange={(e) => {
            setInto(e.target.value);
          }}
          className={field}
        >
          <option value="">(choose a term)</option>
          {targets.map(({ term: t, depth }) => (
            <option key={t.id} value={t.id}>
              {"  ".repeat(depth)}
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className={button}
        disabled={!target || merge.isPending}
        onClick={doMerge}
      >
        Merge
      </button>
      <button
        type="button"
        className={`${button} border-critical text-critical`}
        disabled={remove.isPending}
        onClick={doDelete}
      >
        Delete term
      </button>
      {failed && (
        <p role="alert" className="w-full text-critical">
          {problemText(failed, "The change could not be made.")}
        </p>
      )}
    </div>
  );
}
