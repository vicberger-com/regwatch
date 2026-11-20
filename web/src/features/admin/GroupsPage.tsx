/**
 * `/admin/groups` (M11.4c, CP-27): groups of users, their roles, members and interests.
 * A group's roles apply to its members, so the screen says what adding someone grants. A
 * group never holds users.manage or roles.manage (nor the admin role, which has every
 * permission); the API enforces all of it again.
 */
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useId, useState } from "react";

import { InterestsEditor } from "@/features/me/InterestsEditor";
import { api, type Schemas } from "@/lib/api/client";
import { failure, meQuery, problemText } from "@/lib/auth/session";

import { rolesQuery, usersQuery, type Role } from "./api";

type Group = Schemas["Group"];
const FORBIDDEN = ["users.manage", "roles.manage"];
const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

export const groupsQuery = queryOptions({
  queryKey: ["admin", "groups"],
  queryFn: async (): Promise<Group[]> => {
    const result = await api.GET("/admin/groups");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

function useRefresh() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: groupsQuery.queryKey }),
      // The actor may have changed their own groups: what they may do changes too.
      client.invalidateQueries({ queryKey: meQuery.queryKey }),
    ]);
}

function grantable(role: Role): boolean {
  return !role.permissions.some((p) => FORBIDDEN.includes(p));
}

function permissionsOf(
  roles: readonly Role[],
  keys: readonly string[],
): string[] {
  return [
    ...new Set(
      roles.filter((r) => keys.includes(r.key)).flatMap((r) => r.permissions),
    ),
  ].sort();
}

function RolePicker(props: {
  roles: Role[] | undefined;
  chosen: string[];
  onChange: (keys: string[]) => void;
}) {
  if (!props.roles)
    return (
      <p className="text-sm text-text-muted">
        Choosing roles needs the roles.manage permission to list them. Current
        roles: {props.chosen.join(", ") || "none"}.
      </p>
    );
  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm font-semibold">Roles for every member</legend>
      {props.roles.map((r) => {
        const allowed = grantable(r);
        return (
          <label
            key={r.key}
            className="flex min-h-6 items-center gap-2 text-sm"
          >
            <input
              type="checkbox"
              className="h-5 w-5 shrink-0"
              disabled={!allowed}
              checked={props.chosen.includes(r.key)}
              onChange={(e) => {
                props.onChange(
                  e.target.checked
                    ? [...props.chosen, r.key]
                    : props.chosen.filter((k) => k !== r.key),
                );
              }}
            />
            {r.label}
            {!allowed && (
              <span className="text-text-muted">
                (not for groups: it can manage users or roles; grant it to each
                user)
              </span>
            )}
          </label>
        );
      })}
    </fieldset>
  );
}

function NewGroup({ roles }: { roles: Role[] | undefined }) {
  const id = useId();
  const refresh = useRefresh();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const create = useMutation({
    mutationFn: async () => {
      const result = await api.POST("/admin/groups", {
        body: { key: key.trim(), name: name.trim(), roles: chosen },
      });
      if (!result.response.ok) throw failure(result);
    },
    onSuccess: () => {
      setKey("");
      setName("");
      setChosen([]);
    },
    onSettled: refresh,
  });
  return (
    <form
      aria-label="New group"
      className="grid max-w-xl gap-2 rounded border border-border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <h2 className="text-lg font-semibold">New group</h2>
      <label htmlFor={`${id}-name`} className="text-sm">
        Name
      </label>
      <input
        id={`${id}-name`}
        required
        maxLength={120}
        className={field}
        value={name}
        onChange={(e) => {
          setName(e.target.value);
        }}
      />
      <label htmlFor={`${id}-key`} className="text-sm">
        Key (lower-case letters, digits, - and _)
      </label>
      <input
        id={`${id}-key`}
        required
        pattern="[a-z][a-z0-9_\-]{1,40}"
        className={field}
        value={key}
        onChange={(e) => {
          setKey(e.target.value);
        }}
      />
      <RolePicker roles={roles} chosen={chosen} onChange={setChosen} />
      <div>
        <button type="submit" className={button} disabled={create.isPending}>
          Create the group
        </button>
      </div>
      {create.isError && (
        <p role="alert">
          {problemText(create.error, "The group could not be created.")}
        </p>
      )}
    </form>
  );
}

function GroupDetail({
  group,
  roles,
}: {
  group: Group;
  roles: Role[] | undefined;
}) {
  const id = useId();
  const refresh = useRefresh();
  const users = useQuery(usersQuery);
  const [chosen, setChosen] = useState<string[]>(group.roles);
  const [adding, setAdding] = useState("");
  const call = useMutation({
    mutationFn: async (
      action:
        | { kind: "roles" }
        | { kind: "add" | "remove"; userId: string }
        | { kind: "delete" },
    ) => {
      const path = { params: { path: { id: group.id } } };
      const result =
        action.kind === "roles"
          ? await api.PATCH("/admin/groups/{id}", {
              ...path,
              body: { roles: chosen },
            })
          : action.kind === "delete"
            ? await api.DELETE("/admin/groups/{id}", path)
            : await (action.kind === "add" ? api.PUT : api.DELETE)(
                "/admin/groups/{id}/members/{user_id}",
                { params: { path: { id: group.id, user_id: action.userId } } },
              );
      if (!result.response.ok) throw failure(result);
    },
    onSuccess: () => {
      setAdding("");
    },
    onSettled: refresh,
  });
  const names = new Map(
    (users.data ?? []).map((u) => [u.id, `${u.display_name} (${u.email})`]),
  );
  const grants = roles ? permissionsOf(roles, group.roles) : [];
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="grid max-w-2xl gap-3 rounded border border-border p-3"
    >
      <h2 id={`${id}-title`} className="text-lg font-semibold">
        {group.name}{" "}
        <code className="text-sm text-text-muted">{group.key}</code>
      </h2>
      <RolePicker roles={roles} chosen={chosen} onChange={setChosen} />
      {roles && (
        <div>
          <button
            type="button"
            className={button}
            disabled={call.isPending}
            onClick={() => {
              call.mutate({ kind: "roles" });
            }}
          >
            Save the roles
          </button>
        </div>
      )}
      <h3 className="font-semibold">Members ({group.members.length})</h3>
      {grants.length > 0 && (
        <p className="text-sm text-text-muted">
          Members get: {grants.join(", ")}. You can add or remove members only
          if you hold all of these.
        </p>
      )}
      <ul className="grid gap-1 text-sm">
        {group.members.map((m) => (
          <li key={m} className="flex items-center gap-2">
            <span>{names.get(m) ?? m}</span>
            <button
              type="button"
              className={button}
              aria-label={`Remove ${names.get(m) ?? m} from ${group.name}`}
              disabled={call.isPending}
              onClick={() => {
                call.mutate({ kind: "remove", userId: m });
              }}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-sm">
          Add a member
          <select
            className={field}
            value={adding}
            onChange={(e) => {
              setAdding(e.target.value);
            }}
          >
            <option value="">Choose a user</option>
            {(users.data ?? [])
              .filter((u) => !group.members.includes(u.id))
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name} ({u.email})
                </option>
              ))}
          </select>
        </label>
        <button
          type="button"
          className={button}
          disabled={!adding || call.isPending}
          onClick={() => {
            call.mutate({ kind: "add", userId: adding });
          }}
        >
          Add
        </button>
      </div>
      {call.isError && (
        <p role="alert">
          {problemText(call.error, "The change could not be saved.")}
        </p>
      )}
      <InterestsEditor
        key={JSON.stringify(group.interests ?? {})}
        saved={group.interests}
        title={`${group.name}'s interests`}
        saveLabel="Save the group's interests"
        onSave={async (interests) => {
          const result = await api.PATCH("/admin/groups/{id}", {
            params: { path: { id: group.id } },
            body: { interests },
          });
          if (!result.response.ok) throw failure(result);
          await refresh();
        }}
      />
      <p className="text-sm text-text-muted">
        Members who have set no interests of their own open the map and items
        filtered to these.
      </p>
      <div>
        <button
          type="button"
          className={button}
          disabled={call.isPending}
          onClick={() => {
            if (window.confirm(`Delete the group ${group.name}?`))
              call.mutate({ kind: "delete" });
          }}
        >
          Delete the group
        </button>
      </div>
    </section>
  );
}

export function GroupsPage({ canListRoles }: { canListRoles: boolean }) {
  const groups = useQuery(groupsQuery);
  const roles = useQuery({ ...rolesQuery, enabled: canListRoles });
  const [open, setOpen] = useState<string | null>(null);
  if (groups.isPending) return <p>Loading groups…</p>;
  if (groups.isError)
    return (
      <p role="alert" className="text-critical">
        {problemText(groups.error, "The groups could not be loaded.")}
      </p>
    );
  const current = groups.data.find((g) => g.id === open);
  return (
    <section aria-labelledby="groups-heading" className="flex flex-col gap-4">
      <h1 id="groups-heading" className="text-2xl font-semibold">
        Groups
      </h1>
      <p className="max-w-2xl text-sm text-text-muted">
        A group's roles apply to its members alongside their own, and its
        interests are their default. Managing users and roles is never granted
        through a group.
      </p>
      <ul className="grid gap-2">
        {groups.data.map((g) => (
          <li key={g.id} className="flex items-center gap-3">
            <span className="font-semibold">{g.name}</span>
            <span className="text-sm text-text-muted">
              {g.members.length} members · {g.roles.join(", ") || "no roles"}
            </span>
            <button
              type="button"
              className={button}
              aria-expanded={open === g.id}
              aria-label={`Open ${g.name}`}
              onClick={() => {
                setOpen(open === g.id ? null : g.id);
              }}
            >
              {open === g.id ? "Close" : "Open"}
            </button>
          </li>
        ))}
      </ul>
      {current && (
        <GroupDetail
          key={current.id + current.roles.join()}
          group={current}
          roles={roles.data}
        />
      )}
      <NewGroup roles={roles.data} />
    </section>
  );
}
