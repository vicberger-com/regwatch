import { useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { PublicFrame } from "@/app/PublicFrame";
import { ApiProblem, loginErrorMessage, useLogin } from "@/lib/auth/session";

/** `/login` (screens.md): email, password, sign-in button and an error live region. */
export function LoginPage({ next }: { next?: string | undefined }) {
  const navigate = useNavigate();
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const error =
    login.error instanceof ApiProblem
      ? loginErrorMessage(login.error.problem)
      : login.error
        ? "Sign-in failed. Try again."
        : "";

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate(
      { email, password },
      {
        onSuccess: (me) => {
          setPassword("");
          const target = me.must_change_password
            ? "/change-password"
            : safeNext(next);
          void navigate({ to: target });
        },
      },
    );
  }

  return (
    <PublicFrame screen="Sign in">
      <div className="mx-auto max-w-sm rounded border border-border bg-surface p-6">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <form className="mt-4 flex flex-col gap-3" onSubmit={submit} noValidate>
          <label className="flex flex-col gap-1">
            <span>Email</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
              }}
              className="rounded border border-border bg-bg px-2 py-1"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
              }}
              className="rounded border border-border bg-bg px-2 py-1"
            />
          </label>
          <p role="alert" className="min-h-6 text-critical">
            {error}
          </p>
          <button
            type="submit"
            disabled={login.isPending || !email || !password}
            className="rounded bg-accent px-3 py-2 font-semibold text-accent-contrast disabled:opacity-50"
          >
            {login.isPending ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </PublicFrame>
  );
}

/** Only same-site paths are followed after sign-in (no open redirect). */
export function safeNext(next: string | undefined): string {
  // "/\\host" reads as "//host" in browsers; control characters are never part of a path.
  if (
    !next ||
    !next.startsWith("/") ||
    next.startsWith("//") ||
    /[\\\u0000-\u001f\u007f]/.test(next)
  ) {
    return "/";
  }
  return next;
}
