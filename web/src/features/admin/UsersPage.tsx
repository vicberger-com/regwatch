import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { problemText } from "@/lib/auth/session";

import { usersQuery, useResetPassword, useUpdateUser, type User } from "./api";

const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

/** `/admin/users` (screens.md): table, reset password, enable and disable. */
export function UsersPage({ selfId }: { selfId: string }) {
  const users = useQuery(usersQuery);
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
                  setSecret(null);
                  update.mutate({ id: u.id, body: { status } });
                }}
                onReset={() => {
                  setSecret(null);
                  reset.mutate(u.id, {
                    onSuccess: (password) => {
                      setSecret({ email: u.email, password });
                    },
                  });
                }}
              />
            ))}
          </tbody>
        </table>
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
        <button
          type="button"
          className={button}
          disabled={busy}
          aria-label={`Reset password for ${user.email}`}
          onClick={props.onReset}
        >
          Reset password
        </button>
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
