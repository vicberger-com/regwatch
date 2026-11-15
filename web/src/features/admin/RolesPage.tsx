import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { problemText } from "@/lib/auth/session";

import {
  permissionsQuery,
  rolesQuery,
  useDeleteRole,
  useSaveRole,
  type Permission,
  type Role,
} from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

/** `/admin/roles` (screens.md): role list and a permission matrix grouped by module. */
export function RolesPage() {
  const roles = useQuery(rolesQuery);
  const permissions = useQuery(permissionsQuery);
  const [editing, setEditing] = useState<Role | "new" | null>(null);

  if (roles.isPending || permissions.isPending) return <p>Loading roles…</p>;
  if (roles.isError || permissions.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(
          roles.error ?? permissions.error,
          "Roles could not be loaded.",
        )}
      </p>
    );
  }
  return (
    <section aria-labelledby="roles-heading" className="flex flex-col gap-4">
      <h1 id="roles-heading" className="text-2xl font-semibold">
        Roles
      </h1>
      <ul className="flex flex-col gap-2">
        {roles.data.map((r) => (
          <li key={r.id} className="flex items-center gap-3">
            <span className="font-semibold">{r.label}</span>
            <code className="text-text-muted">{r.key}</code>
            <span className="text-text-muted">
              {r.permissions.length} permissions{r.system ? " · system" : ""}
            </span>
            <button
              type="button"
              className={button}
              aria-label={`Edit ${r.label}`}
              onClick={() => {
                setEditing(r);
              }}
            >
              Edit
            </button>
          </li>
        ))}
      </ul>
      <div>
        <button
          type="button"
          className={button}
          onClick={() => {
            setEditing("new");
          }}
        >
          Create role
        </button>
      </div>
      {editing && (
        <RoleForm
          key={editing === "new" ? "new" : editing.id}
          role={editing === "new" ? null : editing}
          permissions={permissions.data}
          onDone={() => {
            setEditing(null);
          }}
        />
      )}
    </section>
  );
}

function RoleForm(props: {
  role: Role | null;
  permissions: Permission[];
  onDone: () => void;
}) {
  const { role } = props;
  const save = useSaveRole();
  const remove = useDeleteRole();
  const [key, setKey] = useState(role?.key ?? "");
  const [label, setLabel] = useState(role?.label ?? "");
  const [chosen, setChosen] = useState<string[]>(role?.permissions ?? []);
  const locked = role?.system === true && role.key === "admin"; // the API keeps it whole
  const modules = groupByModule(props.permissions);
  const title = role ? `Edit role ${role.label}` : "Create role";

  function submit(event: FormEvent) {
    event.preventDefault();
    const body = {
      label,
      permissions: [...chosen].sort(),
      ...(role ? {} : { key }),
    };
    save.mutate(
      { ...(role ? { id: role.id } : {}), body },
      { onSuccess: props.onDone },
    );
  }

  function onDelete() {
    if (!role || !window.confirm(`Delete the role ${role.label}?`)) return;
    remove.mutate(role.id, { onSuccess: props.onDone });
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label={title}
      className="flex flex-col gap-3 rounded border border-border bg-surface p-4"
    >
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="flex flex-wrap gap-3">
        {!role && (
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
        )}
        <label className="flex flex-col gap-1">
          <span>Label</span>
          <input
            value={label}
            maxLength={120}
            onChange={(e) => {
              setLabel(e.target.value);
            }}
            className={field}
          />
        </label>
      </div>
      {locked && (
        <p className="text-text-muted">
          The admin role always holds every permission.
        </p>
      )}
      {modules.map(([module, perms]) => (
        <fieldset key={module} className="flex flex-col gap-1">
          <legend className="font-semibold">{module}</legend>
          {perms.map((p) => (
            <label key={p.key} className="flex items-center gap-2">
              <input
                type="checkbox"
                disabled={locked}
                checked={chosen.includes(p.key ?? "")}
                onChange={(e) => {
                  const k = p.key ?? "";
                  setChosen(
                    e.target.checked
                      ? [...chosen, k]
                      : chosen.filter((c) => c !== k),
                  );
                }}
              />
              <code>{p.key}</code>
              <span className="text-text-muted">{p.description}</span>
            </label>
          ))}
        </fieldset>
      ))}
      <p role="alert" className="text-critical">
        {problemText(
          save.error ?? remove.error,
          "The role could not be saved.",
        )}
      </p>
      <div className="flex gap-2">
        <button
          type="submit"
          className={button}
          disabled={save.isPending || !label.trim() || (!role && !key)}
        >
          {role ? "Save" : "Create"}
        </button>
        <button type="button" className={button} onClick={props.onDone}>
          Cancel
        </button>
        {role && !role.system && (
          <button
            type="button"
            className={button}
            disabled={remove.isPending}
            onClick={onDelete}
          >
            Delete role
          </button>
        )}
      </div>
    </form>
  );
}

function groupByModule(perms: Permission[]): [string, Permission[]][] {
  const groups = new Map<string, Permission[]>();
  for (const p of perms) {
    const module = p.module ?? "other";
    groups.set(module, [...(groups.get(module) ?? []), p]);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}
