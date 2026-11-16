import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { problemText } from "@/lib/auth/session";

import {
  jurisdictionsQuery,
  KINDS,
  regionsQuery,
  useSaveJurisdiction,
  type Jurisdiction,
} from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";
type Kind = (typeof KINDS)[number];

/** `/admin/jurisdictions` (screens.md): table with an edit form; create for managers. */
export function JurisdictionsPage({ canManage }: { canManage: boolean }) {
  const list = useQuery(jurisdictionsQuery);
  const regions = useQuery(regionsQuery);
  const [kind, setKind] = useState<"" | Kind>("");
  const [editing, setEditing] = useState<Jurisdiction | "new" | null>(null);

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
  // Named and sorted by name, so the parent picker reads "Germany (DE)" (use testing U-M2-1).
  const countries = list.data
    .filter((j) => j.kind === "country")
    .map((j) => ({ code: j.code, name: j.name }))
    .sort((a, b) => a.name.localeCompare(b.name));

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
        {canManage && (
          <button
            type="button"
            className={button}
            onClick={() => {
              setEditing("new");
            }}
          >
            Create jurisdiction
          </button>
        )}
      </div>
      {editing && (
        <JurisdictionForm
          key={editing === "new" ? "new" : editing.code}
          current={editing === "new" ? null : editing}
          regions={regions.data ?? []}
          countries={countries}
          onDone={() => {
            setEditing(null);
          }}
        />
      )}
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">Jurisdictions</caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col">Code</th>
            <th scope="col">Name</th>
            <th scope="col">Kind</th>
            <th scope="col">Region</th>
            <th scope="col">Active</th>
            {canManage && <th scope="col">Actions</th>}
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
              {canManage && (
                <td>
                  <button
                    type="button"
                    className={button}
                    aria-label={`Edit ${j.code}`}
                    onClick={() => {
                      setEditing(j);
                    }}
                  >
                    Edit
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function JurisdictionForm({
  current,
  regions,
  countries,
  onDone,
}: {
  current: Jurisdiction | null;
  regions: { code?: string; name?: string }[];
  countries: { code: string; name: string }[];
  onDone: () => void;
}) {
  const save = useSaveJurisdiction();
  const [code, setCode] = useState(current?.code ?? "");
  const [name, setName] = useState(current?.name ?? "");
  const [kind, setKind] = useState<Kind>(current?.kind ?? "country");
  const [parent, setParent] = useState(current?.parent_code ?? "");
  const [region, setRegion] = useState(current?.region_code ?? "");
  const [geometry, setGeometry] = useState(current?.geometry_ref ?? "");
  const [active, setActive] = useState(current?.active ?? true);
  const title = current ? `Edit ${current.code}` : "Create jurisdiction";

  function submit(event: FormEvent) {
    event.preventDefault();
    const body = {
      name,
      region_code: region || null,
      geometry_ref: geometry.trim() || null,
      active,
      ...(kind === "subdivision" ? { parent_code: parent || null } : {}),
    };
    save.mutate(
      current
        ? { code: current.code, body }
        : { body: { ...body, code, kind } },
      {
        onSuccess: onDone,
      },
    );
  }

  const text = (
    label: string,
    value: string,
    set: (v: string) => void,
    disabled = false,
  ) => (
    <label className="flex flex-col gap-1">
      <span>{label}</span>
      <input
        value={value}
        disabled={disabled}
        onChange={(e) => {
          set(e.target.value);
        }}
        className={field}
      />
    </label>
  );

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label={title}
      className="flex flex-col gap-3 rounded border border-border bg-surface p-3"
    >
      <h2 className="font-semibold">{title}</h2>
      <div className="flex flex-wrap gap-3">
        {text("Code", code, setCode, current !== null)}
        {text("Name", name, setName)}
        <label className="flex flex-col gap-1">
          <span>Kind</span>
          <select
            value={kind}
            disabled={current !== null}
            onChange={(e) => {
              setKind(e.target.value as Kind);
            }}
            className={field}
          >
            {KINDS.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        {kind === "subdivision" && (
          <label className="flex flex-col gap-1">
            <span>Parent country</span>
            <select
              value={parent}
              onChange={(e) => {
                setParent(e.target.value);
              }}
              className={field}
            >
              <option value="">(choose)</option>
              {countries.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name} ({c.code})
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex flex-col gap-1">
          <span>Region</span>
          <select
            value={region}
            onChange={(e) => {
              setRegion(e.target.value);
            }}
            className={field}
          >
            <option value="">(none)</option>
            {regions.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        {text("Map feature id", geometry, setGeometry)}
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
      {save.isError && (
        <p role="alert" className="text-critical">
          {problemText(save.error, "The jurisdiction could not be saved.")}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          className={button}
          disabled={save.isPending || !name.trim()}
        >
          Save
        </button>
        <button type="button" className={button} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
