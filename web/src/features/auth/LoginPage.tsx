import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { PublicFrame } from "@/app/PublicFrame";
import {
  ApiProblem,
  loginErrorMessage,
  needsCode,
  ssoErrorMessage,
  ssoQuery,
  useLogin,
  useMfaSignIn,
} from "@/lib/auth/session";

/** `/login` (screens.md): email, password, sign-in button and an error live region; with
 * `auth.oidc` on, first the organisation's account (M1b), the password form staying for
 * administrators. */
export function LoginPage({
  next,
  sso,
}: {
  next?: string | undefined;
  sso?: string | undefined;
}) {
  const navigate = useNavigate();
  const login = useLogin();
  const ssoOn = useQuery(ssoQuery).data === true;
  const second = useMfaSignIn();
  const [code, setCode] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const error =
    login.error instanceof ApiProblem
      ? loginErrorMessage(login.error.problem)
      : login.error
        ? "Sign-in failed. Try again."
        : ssoErrorMessage(sso);

  function finish(me: {
    must_change_password?: boolean;
    mfa_setup_required?: boolean;
  }) {
    setPassword("");
    setCode("");
    void navigate({ to: landing(me, next) });
  }

  function submitCode(event: FormEvent) {
    event.preventDefault();
    second.mutate(code.trim(), { onSuccess: finish });
  }

  if (needsCode(login.error)) {
    const codeError =
      second.error instanceof ApiProblem
        ? (second.error.problem.detail ??
          loginErrorMessage(second.error.problem))
        : second.error
          ? "Sign-in failed. Try again."
          : "";
    const expired =
      second.error instanceof ApiProblem &&
      second.error.problem.type.endsWith("/mfa-expired");
    return (
      <PublicFrame screen="Sign in">
        <div className="mx-auto max-w-sm rounded border border-border bg-surface p-6">
          <h1 className="text-xl font-semibold">Sign in</h1>
          <form
            className="mt-4 flex flex-col gap-3"
            onSubmit={submitCode}
            noValidate
          >
            <label className="flex flex-col gap-1">
              <span>Code from your authenticator app</span>
              <input
                type="text"
                autoComplete="one-time-code"
                required
                value={code}
                onChange={(e) => {
                  setCode(e.target.value);
                }}
                className="rounded border border-border bg-bg px-2 py-1"
              />
            </label>
            <p className="text-sm text-text-muted">
              Lost your phone? Enter one of your recovery codes instead.
            </p>
            <p role="alert" className="min-h-6 text-critical">
              {codeError}
            </p>
            <button
              type="submit"
              disabled={second.isPending || !code.trim()}
              className="rounded bg-accent px-3 py-2 font-semibold text-accent-contrast disabled:opacity-50"
            >
              {second.isPending ? "Checking…" : "Continue"}
            </button>
            {expired && (
              <button
                type="button"
                className="rounded border border-border px-3 py-2 font-semibold"
                onClick={() => {
                  second.reset();
                  login.reset();
                  setCode("");
                }}
              >
                Start again
              </button>
            )}
          </form>
        </div>
      </PublicFrame>
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate(
      { email, password },
      {
        onSuccess: (me) => {
          setPassword("");
          const target = landing(me, next);
          void navigate({ to: target });
        },
        onError: (failed) => {
          if (needsCode(failed)) setPassword(""); // not kept for the second step
        },
      },
    );
  }

  return (
    <PublicFrame screen="Sign in">
      <div className="mx-auto max-w-sm rounded border border-border bg-surface p-6">
        <h1 className="text-xl font-semibold">Sign in</h1>
        {ssoOn && (
          <>
            <a
              href={`/api/v1/auth/oidc/login?next=${encodeURIComponent(safeNext(next))}`}
              className="mt-4 block rounded bg-accent px-3 py-2 text-center font-semibold text-accent-contrast"
            >
              Sign in with your organisation&apos;s account
            </a>
            <p className="mt-4 text-sm text-text-muted">
              Administrators can also sign in with a password.
            </p>
          </>
        )}
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
            className={
              ssoOn
                ? "rounded border border-border px-3 py-2 font-semibold disabled:opacity-50"
                : "rounded bg-accent px-3 py-2 font-semibold text-accent-contrast disabled:opacity-50"
            }
          >
            {login.isPending ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </PublicFrame>
  );
}

/** Where a sign-in leads: a forced password change, then a forced two-factor set-up (CP-40),
 * then the page the user asked for. */
export function landing(
  me: { must_change_password?: boolean; mfa_setup_required?: boolean },
  next: string | undefined,
): string {
  if (me.must_change_password) return "/change-password";
  if (me.mfa_setup_required) return "/setup-two-factor";
  return safeNext(next);
}

/** Only same-site paths are followed after sign-in (no open redirect). */
export function safeNext(next: string | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return "/";
  // "/\\host" reads as "//host" in browsers; control characters are never part of a path.
  for (const ch of next) {
    const code = ch.charCodeAt(0);
    if (ch === "\\" || code < 0x20 || code === 0x7f) return "/";
  }
  return next;
}
