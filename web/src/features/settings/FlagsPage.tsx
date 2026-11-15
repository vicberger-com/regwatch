import { useQuery } from "@tanstack/react-query";

import { problemText } from "@/lib/auth/session";

import { flagsQuery, useSetFlag } from "./api";

/** `/admin/flags` (screens.md): toggle list with descriptions; preconditions come from the API. */
export function FlagsPage() {
  const flags = useQuery(flagsQuery);
  const setFlag = useSetFlag();

  if (flags.isPending) return <p>Loading feature flags…</p>;
  if (flags.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(flags.error, "Feature flags could not be loaded.")}
      </p>
    );
  }
  return (
    <section aria-labelledby="flags-heading" className="flex flex-col gap-4">
      <h1 id="flags-heading" className="text-2xl font-semibold">
        Feature flags
      </h1>
      <p role="alert" className="text-critical">
        {problemText(setFlag.error, "The flag could not be changed.")}
      </p>
      <ul className="flex flex-col gap-3">
        {flags.data.map((f) => (
          <li key={f.key} className="flex items-start gap-3">
            <input
              id={`flag-${f.key}`}
              type="checkbox"
              role="switch"
              aria-checked={f.enabled}
              checked={f.enabled}
              disabled={setFlag.isPending}
              aria-describedby={`flag-${f.key}-desc`}
              onChange={(e) => {
                setFlag.mutate({ key: f.key, enabled: e.target.checked });
              }}
              className="mt-1"
            />
            <div>
              <label htmlFor={`flag-${f.key}`} className="font-semibold">
                <code>{f.key}</code>
              </label>
              <p id={`flag-${f.key}-desc`} className="text-text-muted">
                {f.description}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
