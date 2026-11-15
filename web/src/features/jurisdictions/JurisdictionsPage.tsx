import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { problemText } from "@/lib/auth/session";

import { jurisdictionsQuery, KINDS, regionsQuery } from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
type Kind = (typeof KINDS)[number];

/** `/admin/jurisdictions` (screens.md): table of jurisdictions, filterable by kind. */
export function JurisdictionsPage() {
  const list = useQuery(jurisdictionsQuery);
  const regions = useQuery(regionsQuery);
  const [kind, setKind] = useState<"" | Kind>("");

  if (list.isPending) return <p>Loading jurisdictions…</p>;
  if (list.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(list.error, "The jurisdictions could not be loaded.")}
      </p>
    );
  }
  const regionName = new Map((regions.data ?? []).map((r) => [r.code, r.name]));
  const shown = list.data
    .filter((j) => !kind || j.kind === kind)
    .sort((a, b) => a.code.localeCompare(b.code));

  return (
    <section aria-labelledby="jur-heading" className="flex flex-col gap-4">
      <h1 id="jur-heading" className="text-2xl font-semibold">
        Jurisdictions
      </h1>
      <div className="flex items-end gap-3">
        <label className="flex flex-col gap-1">
          <span>Kind</span>
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as "" | Kind);
            }}
            className={field}
          >
            <option value="">All</option>
            {KINDS.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
      </div>
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">Jurisdictions</caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col">Code</th>
            <th scope="col">Name</th>
            <th scope="col">Kind</th>
            <th scope="col">Region</th>
            <th scope="col">Active</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((j) => (
            <tr key={j.id} className="border-b border-border">
              <td>
                <code>{j.code}</code>
              </td>
              <td>{j.name}</td>
              <td>
                {j.kind}
                {j.parent_code ? ` of ${j.parent_code}` : ""}
              </td>
              <td>
                {j.region_code
                  ? (regionName.get(j.region_code) ?? j.region_code)
                  : ""}
              </td>
              <td>{j.active ? "Yes" : "No"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
