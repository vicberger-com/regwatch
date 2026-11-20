import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import { HelpTip } from "@/features/help/HelpTip";
import { meTopic } from "@/features/help/topics";
import { api, type Schemas } from "@/lib/api/client";
import { failure, problemText } from "@/lib/auth/session";

import { useSavePreferences } from "./api";

export type Interests = Schemas["Interests"];

export const interestOptionsQuery = {
  queryKey: ["me", "interest-options"],
  queryFn: async (): Promise<Schemas["InterestOptions"]> => {
    const result = await api.GET("/me/interest-options");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
  staleTime: 5 * 60_000,
};

function toggle(list: readonly string[], value: string, on: boolean): string[] {
  return on ? [...new Set([...list, value])] : list.filter((v) => v !== value);
}

function Checks(props: {
  legend: string;
  options: readonly { key: string; label: string }[];
  chosen: readonly string[];
  onChange: (next: string[]) => void;
  filter?: boolean;
}) {
  const [find, setFind] = useState("");
  const shown = props.filter
    ? props.options.filter((o) =>
        o.label.toLowerCase().includes(find.trim().toLowerCase()),
      )
    : props.options;
  return (
    <fieldset className="rounded border border-border p-3">
      <legend className="px-1 font-semibold">{props.legend}</legend>
      {props.filter && (
        <label className="mb-2 flex flex-col text-sm">
          Find
          <input
            type="search"
            value={find}
            onChange={(e) => {
              setFind(e.target.value);
            }}
            className="mt-1 w-64 rounded border border-border bg-surface px-2 py-1"
          />
        </label>
      )}
      <div className="grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2">
        {shown.map((o) => (
          <label
            key={o.key}
            className="flex min-h-6 items-center gap-2 text-sm"
          >
            <input
              type="checkbox"
              className="h-5 w-5 shrink-0" // 24 px targets with the gap (WCAG 2.5.8)
              checked={props.chosen.includes(o.key)}
              onChange={(e) => {
                props.onChange(toggle(props.chosen, o.key, e.target.checked));
              }}
            />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * "My interests" (M11.1, ADR-0012): regions, jurisdictions and topics that the map, the items
 * list and search open filtered to. They never limit what the user may see.
 */
export function InterestsEditor({
  saved,
  title = "My interests",
  saveLabel = "Save my interests",
  onSave,
}: {
  saved: Interests | undefined;
  title?: string;
  saveLabel?: string;
  /** Saves somewhere else than the user's preferences, such as a group (M11.4c). */
  onSave?: (interests: Interests) => Promise<unknown>;
}) {
  const headingId = useId();
  const options = useQuery(interestOptionsQuery);
  const own = useSavePreferences();
  const other = useMutation({
    mutationFn: (interests: Interests) =>
      onSave ? onSave(interests) : Promise.resolve(),
  });
  const save = onSave ? other : own;
  const [draft, setDraft] = useState<Interests>(() => ({
    jurisdictions: saved?.jurisdictions ?? [],
    regions: saved?.regions ?? [],
    terms: saved?.terms ?? {},
  }));
  if (options.isPending) return <p role="status">Loading the choices…</p>;
  if (options.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(options.error, "The choices could not be loaded.")}
      </p>
    );
  }
  const o = options.data;
  const count =
    (draft.jurisdictions?.length ?? 0) +
    (draft.regions?.length ?? 0) +
    Object.values(draft.terms ?? {}).reduce((n, keys) => n + keys.length, 0);
  return (
    <form
      aria-labelledby={headingId}
      className="grid gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (onSave) other.mutate(draft);
        else own.mutate({ interests: draft });
      }}
    >
      <div className="flex items-center gap-1">
        <h3 id={headingId} className="font-semibold">
          {title}
        </h3>
        <HelpTip id={meTopic("interests")} />
      </div>
      <p className="text-sm text-text-muted">
        The map, items and search open filtered to these; you can always show
        everything.
      </p>
      <Checks
        legend="Regions"
        options={o.regions}
        chosen={draft.regions ?? []}
        onChange={(regions) => {
          setDraft({ ...draft, regions });
        }}
      />
      <Checks
        legend="Jurisdictions"
        filter
        options={o.jurisdictions.map((j) => ({ key: j.code, label: j.name }))}
        chosen={draft.jurisdictions ?? []}
        onChange={(jurisdictions) => {
          setDraft({ ...draft, jurisdictions });
        }}
      />
      {o.facets
        .filter((f) => f.terms.length > 0)
        .map((f) => (
          <Checks
            key={f.key}
            legend={f.label}
            options={f.terms}
            chosen={draft.terms?.[f.key] ?? []}
            onChange={(keys) => {
              setDraft({ ...draft, terms: { ...draft.terms, [f.key]: keys } });
            }}
          />
        ))}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={save.isPending}
          className="rounded bg-accent px-3 py-1 text-accent-contrast"
        >
          {saveLabel}
        </button>
        <span role="status" className="text-sm text-text-muted">
          {save.isSuccess
            ? `Saved: ${String(count)} chosen.`
            : `${String(count)} chosen`}
        </span>
      </div>
      {save.isError && (
        <p role="alert" className="text-critical">
          {problemText(save.error, "The interests could not be saved.")}
        </p>
      )}
    </form>
  );
}
