import { useState, type FormEvent, type ReactNode } from "react";

import { problemText } from "@/lib/auth/session";

import { RuleTest } from "./RuleTest";
import { lines, useUpdateTerm, type MatchRules, type Term } from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

/** Edit a term's label, synonyms and match rules, and try the saved rules on sample text. */
export function TermEditor({
  term,
  onClose,
}: {
  term: Term;
  onClose: () => void;
}) {
  const update = useUpdateTerm();
  const rules: Partial<MatchRules> = term.match_rules ?? {};
  const [label, setLabel] = useState(term.label);
  const [synonyms, setSynonyms] = useState((term.synonyms ?? []).join("\n"));
  const [keywords, setKeywords] = useState((rules.keywords ?? []).join("\n"));
  const [regex, setRegex] = useState((rules.regex ?? []).join("\n"));
  const [languages, setLanguages] = useState(
    (rules.languages ?? []).join(", "),
  );
  const [minHits, setMinHits] = useState(String(rules.min_hits ?? 1));
  const [weight, setWeight] = useState(String(rules.weight ?? 1));
  const [active, setActive] = useState(term.active);
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    const hits = Number(minHits);
    const w = Number(weight);
    const problem =
      !Number.isInteger(hits) || hits < 1
        ? "Minimum hits is a whole number of 1 or more."
        : weight.trim() === "" || !Number.isFinite(w) || w < 0
          ? "Weight is a number of zero or more."
          : null;
    setError(problem);
    if (problem) return;
    update.mutate({
      id: term.id,
      body: {
        label,
        active,
        synonyms: lines(synonyms),
        match_rules: {
          keywords: lines(keywords),
          regex: lines(regex),
          languages: languages
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          min_hits: hits,
          weight: w,
        },
      },
    });
  }

  const area = (
    label: string,
    value: string,
    set: (v: string) => void,
    hint: ReactNode,
  ) => (
    <label className="flex flex-col gap-1">
      <span>
        {label} <span className="text-sm text-text-muted">{hint}</span>
      </span>
      <textarea
        rows={3}
        value={value}
        onChange={(e) => {
          set(e.target.value);
        }}
        className={`${field} font-mono`}
      />
    </label>
  );
  const input = (label: string, value: string, set: (v: string) => void) => (
    <label className="flex flex-col gap-1">
      <span>{label}</span>
      <input
        value={value}
        onChange={(e) => {
          set(e.target.value);
        }}
        className={field}
      />
    </label>
  );
  const message =
    error ??
    (update.isError
      ? problemText(update.error, "The term could not be saved.")
      : null);

  return (
    <div className="flex flex-col gap-3 rounded border border-border bg-surface p-3">
      <form
        onSubmit={submit}
        noValidate
        aria-label={`Edit term ${term.label}`}
        className="flex flex-col gap-3"
      >
        <h3 className="font-semibold">
          Edit term <code>{term.key}</code>
        </h3>
        {input("Label", label, setLabel)}
        {area("Synonyms", synonyms, setSynonyms, "one per line")}
        {area("Keywords", keywords, setKeywords, "one per line")}
        {area(
          "Patterns",
          regex,
          setRegex,
          "one RE2 pattern per line; \\w and \\b match ASCII only, so list words in other languages as keywords instead",
        )}
        <div className="flex flex-wrap gap-3">
          {input("Languages (comma-separated)", languages, setLanguages)}
          {input("Minimum hits", minHits, setMinHits)}
          {input("Weight", weight, setWeight)}
        </div>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => {
              setActive(e.target.checked);
            }}
          />
          Active
        </label>
        {message && (
          <p role="alert" className="text-critical">
            {message}
          </p>
        )}
        <p role="status">{update.isSuccess ? "Saved." : ""}</p>
        <div className="flex gap-2">
          <button
            type="submit"
            className={button}
            disabled={update.isPending || !label.trim()}
          >
            Save term
          </button>
          <button type="button" className={button} onClick={onClose}>
            Close
          </button>
        </div>
      </form>
      <RuleTest term={term} />
    </div>
  );
}
