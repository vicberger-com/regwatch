import { useState, type FormEvent } from "react";

import { problemText } from "@/lib/auth/session";

import { useTestRules, type Term } from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";
const SAMPLE_MAX = 50_000;

/** Runs a term's saved rules on sample text; evidence is shown as text. */
export function RuleTest({ term }: { term: Term }) {
  const test = useTestRules();
  const [text, setText] = useState("");
  const [language, setLanguage] = useState("");
  const result = test.data;

  function submit(event: FormEvent) {
    event.preventDefault();
    test.mutate({
      id: term.id,
      text,
      ...(language.trim() ? { language: language.trim() } : {}),
    });
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label="Test rules"
      className="flex flex-col gap-2"
    >
      <h4 className="font-semibold">
        Test the saved rules against sample text
      </h4>
      <textarea
        aria-label="Sample text"
        rows={4}
        maxLength={SAMPLE_MAX}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
        }}
        className={field}
      />
      <label className="flex flex-col gap-1">
        <span>Language of the sample (optional)</span>
        <input
          value={language}
          onChange={(e) => {
            setLanguage(e.target.value);
          }}
          className={field}
        />
      </label>
      <button
        type="submit"
        className={button}
        disabled={test.isPending || !text.trim()}
      >
        Test
      </button>
      {test.isError && (
        <p role="alert" className="text-critical">
          {problemText(test.error, "The rules could not be tested.")}
        </p>
      )}
      {result && (
        <div role="status">
          <p>
            {result.matched ? "Matched" : "No match"}
            {result.confidence !== undefined
              ? `, confidence ${result.confidence.toFixed(2)}`
              : ""}
          </p>
          {result.evidence && result.evidence.length > 0 && (
            <ul aria-label="Evidence" className="ml-4 list-disc">
              {result.evidence.map((e, i) => (
                <li key={i}>
                  <code>{e}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </form>
  );
}
