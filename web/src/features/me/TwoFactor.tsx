/**
 * Two-factor sign-in on the User tab (BL-148; CP-38): turn it on with an authenticator app (a
 * QR code or the key as text, then a first code), see the recovery codes once, get new ones,
 * or turn it off. Each change asks for the password again; turning off and new codes also ask
 * for a code.
 */
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { failure, problemText } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/time/format";

type Setup = Schemas["MfaSetup"];

export const mfaQuery = queryOptions({
  queryKey: ["me", "mfa"],
  queryFn: async (): Promise<Schemas["MfaStatus"]> => {
    const result = await api.GET("/me/mfa");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
});

const button =
  "rounded border border-border px-3 py-1 font-semibold disabled:opacity-50";
const field = "rounded border border-border bg-bg px-2 py-1";

/** The QR code as squares: dark on light whatever the theme, as scanners expect. */
export function QrCode({ rows, label }: { rows: string[]; label: string }) {
  const size = rows.length + 8; // a quiet zone of four modules each side
  const path = rows
    .flatMap((row, y) =>
      Array.from({ length: row.length }, (_, x) => row.charAt(x)).map(
        (cell, x) =>
          cell === "1" ? `M${String(x + 4)} ${String(y + 4)}h1v1h-1z` : "",
      ),
    )
    .join("");
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${String(size)} ${String(size)}`}
      width="200"
      height="200"
      shapeRendering="crispEdges"
    >
      <rect width={size} height={size} fill="#ffffff" />
      <path d={path} fill="#000000" />
    </svg>
  );
}

function RecoveryList({
  codes,
  onDone,
}: {
  codes: string[];
  onDone: () => void;
}) {
  return (
    <div className="grid gap-2" role="region" aria-label="Recovery codes">
      <p>
        Keep these recovery codes somewhere safe. Each one signs you in once if
        you lose your phone. They are shown only now.
      </p>
      <ul className="grid grid-cols-2 gap-1 font-mono">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <button type="button" className={button} onClick={onDone}>
        I have saved them
      </button>
    </div>
  );
}

function Labelled(props: {
  label: string;
  type: "password" | "text";
  value: string;
  onChange: (v: string) => void;
  autoComplete: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id}>{props.label}</label>
      <input
        id={id}
        type={props.type}
        autoComplete={props.autoComplete}
        value={props.value}
        onChange={(e) => {
          props.onChange(e.target.value);
        }}
        className={field}
      />
    </div>
  );
}

export function TwoFactor() {
  const client = useQueryClient();
  const status = useQuery(mfaQuery);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [setup, setSetup] = useState<Setup | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [mode, setMode] = useState<"idle" | "off" | "renew">("idle");
  const refresh = () =>
    client.invalidateQueries({ queryKey: mfaQuery.queryKey });
  const clear = () => {
    setPassword("");
    setCode("");
  };

  const start = useMutation({
    gcTime: 0, // holds a secret or recovery codes: not kept after unmount
    mutationFn: async () => {
      const result = await api.POST("/me/mfa/setup", { body: { password } });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data;
    },
    onSuccess: (found) => {
      clear();
      setSetup(found);
    },
  });
  const confirm = useMutation({
    gcTime: 0, // holds a secret or recovery codes: not kept after unmount
    mutationFn: async () => {
      const result = await api.POST("/me/mfa/confirm", { body: { code } });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data.recovery_codes;
    },
    onSuccess: (found) => {
      clear();
      setSetup(null);
      setCodes(found);
      void refresh();
    },
  });
  const change = useMutation({
    gcTime: 0, // holds a secret or recovery codes: not kept after unmount
    mutationFn: async (what: "off" | "renew") => {
      const body = { password, code };
      if (what === "off") {
        const result = await api.POST("/me/mfa/disable", { body });
        if (!result.response.ok) throw failure(result);
        return null;
      }
      const result = await api.POST("/me/mfa/recovery-codes", { body });
      if (!result.response.ok || result.data === undefined)
        throw failure(result);
      return result.data.recovery_codes;
    },
    onSuccess: (found) => {
      clear();
      setMode("idle");
      setCodes(found);
      void refresh();
    },
  });
  const pending = start.isPending || confirm.isPending || change.isPending;
  const error = problemText(
    start.error ?? confirm.error ?? change.error,
    "The change was refused.",
  );

  if (codes)
    return (
      <RecoveryList
        codes={codes}
        onDone={() => {
          setCodes(null);
        }}
      />
    );
  if (status.isPending) return <p>Loading…</p>;
  if (status.isError)
    return <p role="alert">Two-factor sign-in cannot be shown.</p>;

  const submit = (run: () => void) => (event: FormEvent) => {
    event.preventDefault();
    run();
  };
  const message = (
    <p role="alert" className="min-h-6 text-critical">
      {error}
    </p>
  );

  if (status.data.enabled) {
    return (
      <div className="grid gap-3">
        <p>
          On since{" "}
          {status.data.confirmed_at
            ? formatDateTime(status.data.confirmed_at)
            : "an earlier sign-in"}
          . {String(status.data.recovery_codes_left)} recovery code
          {status.data.recovery_codes_left === 1 ? "" : "s"} left.
        </p>
        {mode === "idle" ? (
          <div className="flex gap-2">
            <button
              type="button"
              className={button}
              onClick={() => {
                change.reset();
                setMode("renew");
              }}
            >
              New recovery codes
            </button>
            <button
              type="button"
              className={button}
              onClick={() => {
                change.reset();
                setMode("off");
              }}
            >
              Turn off
            </button>
          </div>
        ) : (
          <form
            className="grid gap-2"
            aria-label={
              mode === "off"
                ? "Turn off two-factor sign-in"
                : "New recovery codes"
            }
            onSubmit={submit(() => {
              change.mutate(mode);
            })}
          >
            <Labelled
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
            />
            <Labelled
              label="Code from your authenticator app"
              type="text"
              value={code}
              onChange={setCode}
              autoComplete="one-time-code"
            />
            {message}
            <div className="flex gap-2">
              <button
                type="submit"
                className={button}
                disabled={pending || !password || !code}
              >
                {mode === "off" ? "Turn off" : "Get new codes"}
              </button>
              <button
                type="button"
                className={button}
                onClick={() => {
                  clear();
                  setMode("idle");
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    );
  }

  if (setup) {
    const key = setup.secret.replace(/(.{4})/g, "$1 ").trim();
    return (
      <form
        className="grid gap-3"
        aria-label="Set up two-factor sign-in"
        onSubmit={submit(() => {
          confirm.mutate();
        })}
      >
        <p>
          Scan the code with an authenticator app, or type the key into it. Then
          enter the six-digit code it shows.
        </p>
        <QrCode rows={setup.qr} label="QR code for your authenticator app" />
        <p>
          Key: <code className="font-mono">{key}</code>
        </p>
        <Labelled
          label="Code from your authenticator app"
          type="text"
          value={code}
          onChange={setCode}
          autoComplete="one-time-code"
        />
        {message}
        <div className="flex gap-2">
          <button type="submit" className={button} disabled={pending || !code}>
            Turn on
          </button>
          <button
            type="button"
            className={button}
            onClick={() => {
              clear();
              setSetup(null);
            }}
          >
            Cancel
          </button>
        </div>
      </form>
    );
  }

  return (
    <form
      className="grid gap-2"
      aria-label="Start two-factor sign-in"
      onSubmit={submit(() => {
        start.mutate();
      })}
    >
      <p>
        Off. With it on, signing in also asks for a code from an app on your
        phone.
      </p>
      <Labelled
        label="Password"
        type="password"
        value={password}
        onChange={setPassword}
        autoComplete="current-password"
      />
      {message}
      <button type="submit" className={button} disabled={pending || !password}>
        Set up
      </button>
    </form>
  );
}
