import { useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { ApiProblem, useChangePassword } from "@/lib/auth/session";

const MIN_LENGTH = 12;

/** Password change (screens.md `/me`, Password section); forced after a temporary password. */
export function ChangePasswordPage({ forced }: { forced: boolean }) {
  const navigate = useNavigate();
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [local, setLocal] = useState("");

  const serverError =
    change.error instanceof ApiProblem
      ? (change.error.problem.detail ?? "The password could not be changed.")
      : change.error
        ? "The password could not be changed."
        : "";

  function submit(event: FormEvent) {
    event.preventDefault();
    if (next.length < MIN_LENGTH) {
      setLocal(
        `The new password needs at least ${String(MIN_LENGTH)} characters.`,
      );
      return;
    }
    if (next !== repeat) {
      setLocal("The new passwords do not match.");
      return;
    }
    setLocal("");
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          void navigate({ to: "/" });
        },
      },
    );
  }

  const field = "rounded border border-border bg-bg px-2 py-1";
  return (
    <div className="mx-auto mt-10 max-w-sm rounded border border-border bg-surface p-6">
      <h1 className="text-xl font-semibold">Change password</h1>
      {forced && (
        <p className="mt-2 text-text-muted">
          You signed in with a temporary password. Choose your own to continue.
        </p>
      )}
      <form className="mt-4 flex flex-col gap-3" onSubmit={submit} noValidate>
        <label className="flex flex-col gap-1">
          <span>Current password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => {
              setCurrent(e.target.value);
            }}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>New password (at least {String(MIN_LENGTH)} characters)</span>
          <input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => {
              setNext(e.target.value);
            }}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Repeat new password</span>
          <input
            type="password"
            autoComplete="new-password"
            value={repeat}
            onChange={(e) => {
              setRepeat(e.target.value);
            }}
            className={field}
          />
        </label>
        <p role="alert" className="min-h-6 text-critical">
          {local || serverError}
        </p>
        <button
          type="submit"
          disabled={change.isPending || !current || !next}
          className="rounded bg-accent px-3 py-2 font-semibold text-accent-contrast disabled:opacity-50"
        >
          {change.isPending ? "Saving…" : "Change password"}
        </button>
      </form>
    </div>
  );
}
