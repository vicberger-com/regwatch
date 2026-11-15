import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { problemText } from "@/lib/auth/session";

import {
  MAX_USERS,
  rolesQuery,
  usersQuery,
  useCreateUser,
  useResetPassword,
  useUpdateUser,
  type User,
} from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

/** `/admin/users` (screens.md): table, create form, reset password, enable and disable. */
export function UsersPage({ selfId }: { selfId: string }) {
  const users = useQuery(usersQuery);
  const roles = useQuery(rolesQuery);
  const update = useUpdateUser();
  const reset = useResetPassword();
  // A temporary password is shown once, here, and dropped when the next action starts.
  const [secret, setSecret] = useState<{
    email: string;
    password: string;
  } | null>(null);

  const error = problemText(
    update.error ?? reset.error,
    "The change was refused.",
  );

  return (
    <section aria-labelledby="users-heading" className="flex flex-col gap-4">
      <h1 id="users-heading" className="text-2xl font-semibold">
        Users
      </h1>
      <CreateUser
        roleKeys={(roles.data ?? []).map((r) => r.key)}
        rolesUnavailable={roles.isError}
        onCreated={(email, password) => {
          setSecret({ email, password });
        }}
      />
      <div role="status" aria-live="polite">
        {secret && (
          <p className="rounded border border-warning bg-surface p-3">
            Temporary password for {secret.email}:{" "}
            <code>{secret.password}</code>. It is shown once; the user must
            change it at first sign-in.
          </p>
        )}
      </div>
      <p role="alert" className="text-critical">
        {error}
      </p>
      {users.isPending ? (
        <p>Loading users…</p>
      ) : users.isError ? (
        <p role="alert" className="text-critical">
          {problemText(users.error, "Users could not be loaded.")}
        </p>
      ) : (
        <>
          {users.data.length >= MAX_USERS && (
            <p role="status" className="text-warning">
              Only the first {String(MAX_USERS)} users are listed
              (re-verification N3).
            </p>
          )}
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">Users</caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Roles</th>
                <th scope="col">Status</th>
                <th scope="col">Last sign-in</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) => (
                <Row
                  key={u.id}
                  user={u}
                  isSelf={u.id === selfId}
                  busy={update.isPending || reset.isPending}
                  onStatus={(status) => {
                    const verb = status === "disabled" ? "Disable" : "Enable";
                    if (!window.confirm(`${verb} ${u.email}?`)) return;
                    setSecret(null);
                    update.mutate({ id: u.id, body: { status } });
                  }}
                  onReset={() => {
                    const ask = `Reset the password of ${u.email}? This ends all their sessions.`;
                    if (!window.confirm(ask)) return;
                    setSecret(null);
                    reset.mutate(u.id, {
                      onSuccess: (password) => {
                        setSecret({ email: u.email, password });
                        reset.reset(); // the shown copy is the only one (re-verification N1)
                      },
                    });
                  }}
                />
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

function Row(props: {
  user: User;
  isSelf: boolean;
  busy: boolean;
  onStatus: (status: "active" | "disabled") => void;
  onReset: () => void;
}) {
  const { user, isSelf, busy } = props;
  const active = user.status === "active";
  return (
    <tr className="border-b border-border">
      <td>{user.display_name}</td>
      <td>{user.email}</td>
      <td>{user.roles.join(", ") || "none"}</td>
      <td>{user.status}</td>
      <td>
        {user.last_login_at
          ? new Date(user.last_login_at).toLocaleString()
          : "never"}
      </td>
      <td className="flex gap-2 py-1">
        {!isSelf && (
          <button
            type="button"
            className={button}
            disabled={busy}
            aria-label={`Reset password for ${user.email}`}
            onClick={props.onReset}
          >
            Reset password
          </button>
        )}
        {!isSelf && (
          <button
            type="button"
            className={button}
            disabled={busy}
            aria-label={`${active ? "Disable" : "Enable"} ${user.email}`}
            onClick={() => {
              props.onStatus(active ? "disabled" : "active");
            }}
          >
            {active ? "Disable" : "Enable"}
          </button>
        )}
      </td>
    </tr>
  );
}

function CreateUser(props: {
  roleKeys: string[];
  rolesUnavailable: boolean;
  onCreated: (email: string, password: string) => void;
}) {
  const create = useCreateUser();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      { email, display_name: name, roles: chosen },
      {
        onSuccess: (user) => {
          props.onCreated(user.email, user.temporary_password ?? "");
          create.reset(); // the shown copy is the only one (re-verification N1)
          setEmail("");
          setName("");
          setChosen([]);
        },
      },
    );
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-labelledby="create-user-heading"
      className="flex flex-col gap-2 rounded border border-border bg-surface p-4"
    >
      <h2 id="create-user-heading" className="text-lg font-semibold">
        Create user
      </h2>
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
            }}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Name</span>
          <input
            value={name}
            maxLength={120}
            onChange={(e) => {
              setName(e.target.value);
            }}
            className={field}
          />
        </label>
      </div>
      <fieldset className="flex flex-wrap gap-3">
        <legend>Roles</legend>
        {props.rolesUnavailable && (
          <p className="text-text-muted">
            The role list needs the roles.manage permission; users are created
            without roles.
          </p>
        )}
        {props.roleKeys.map((key) => (
          <label key={key} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={chosen.includes(key)}
              onChange={(e) => {
                setChosen(
                  e.target.checked
                    ? [...chosen, key]
                    : chosen.filter((k) => k !== key),
                );
              }}
            />
            {key}
          </label>
        ))}
      </fieldset>
      <p role="alert" className="text-critical">
        {problemText(create.error, "The user could not be created.")}
      </p>
      <div>
        <button
          type="submit"
          className={button}
          disabled={create.isPending || !email || !name.trim()}
        >
          {create.isPending ? "Creating…" : "Create user"}
        </button>
      </div>
    </form>
  );
}
