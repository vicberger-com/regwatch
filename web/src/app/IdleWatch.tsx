import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { preferencesQuery } from "@/features/me/api";
import { api } from "@/lib/api/client";
import { forgetEverything, useLogout } from "@/lib/auth/session";

const WARNING_S = 60;
/** The server renews last activity at most once a minute (identity TOUCH_INTERVAL), so the
 * client ends a minute early: its countdown never outlasts the server's session. */
const SERVER_SLACK_S = 60;
const ACTIVITY = ["keydown", "pointerdown", "wheel", "touchstart"] as const;
const SHARED_KEY = "regwatch.activity"; // the last input in any tab of this browser
const ANNOUNCE_AT = new Set([60, 30, 10]);

function sharedLast(): number {
  try {
    return Number(window.localStorage.getItem(SHARED_KEY)) || 0;
  } catch {
    return 0;
  }
}

function share(at: number): void {
  try {
    window.localStorage.setItem(SHARED_KEY, String(at));
  } catch {
    // this tab alone then
  }
}

/**
 * M9 acceptance 2: shortly before the idle timeout in force, a dialog warns that the session
 * will end and counts down; at zero the user is signed out. Input in any tab of the browser
 * counts. "Stay signed in" asks the API, which renews the session, and checks the answer. The
 * API enforces the timeout on its own; this only makes it visible, and never lengthens it.
 */
export function IdleWatch() {
  const prefs = useQuery(preferencesQuery);
  // Unknown timeout (the preferences failed): no client countdown; the server still enforces.
  const minutes = prefs.isSuccess
    ? (prefs.data.session_idle_timeout_minutes ?? null)
    : null;
  const logout = useLogout();
  const client = useQueryClient();
  const navigate = useNavigate();
  const last = useRef(0);
  const [left, setLeft] = useState<number | null>(null);
  const [said, setSaid] = useState("");
  const stay = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);

  /** Sign out here whatever the server says: nothing of this user stays on screen. */
  const signOut = useCallback(
    (next?: string) => {
      logout.mutate(undefined); // best effort; the server's own timeout ends it otherwise
      forgetEverything(client);
      void navigate({ to: "/login", search: next ? { next } : {} });
    },
    [logout, client, navigate],
  );

  useEffect(() => {
    if (minutes === null) return;
    if (last.current === 0) {
      last.current = Math.max(Date.now(), sharedLast());
      share(last.current);
    }
    const touch = () => {
      if (left !== null) return; // while warning, only the dialog's buttons count
      last.current = Date.now();
      share(last.current);
    };
    for (const name of ACTIVITY)
      window.addEventListener(name, touch, { passive: true });
    const tick = window.setInterval(() => {
      last.current = Math.max(last.current, sharedLast());
      const remaining = Math.ceil(
        minutes * 60 - SERVER_SLACK_S - (Date.now() - last.current) / 1000,
      );
      if (remaining <= 0) {
        window.clearInterval(tick);
        signOut();
      } else if (remaining <= WARNING_S) {
        setLeft(remaining);
        if (ANNOUNCE_AT.has(remaining))
          setSaid(`Signing out in ${String(remaining)} seconds.`);
      } else if (left !== null) {
        setLeft(null); // another tab saw input
      }
    }, 1000);
    return () => {
      for (const name of ACTIVITY) window.removeEventListener(name, touch);
      window.clearInterval(tick);
    };
  }, [minutes, left, signOut]);

  const keep = useCallback(async () => {
    const got = await api.GET("/auth/me");
    if (got.response.status === 401) {
      signOut(window.location.pathname + window.location.search); // the server ended it
      return;
    }
    last.current = Date.now();
    share(last.current);
    setLeft(null);
    setSaid("");
  }, [signOut]);

  const open = left !== null;
  // Opening: remember focus, make the page behind inert, focus "Stay"; closing: undo both.
  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    // Everything outside the dialog (its portal is a direct child of body) becomes inert.
    const behind = [...document.body.children].filter(
      (el) => !el.contains(box.current) && !el.hasAttribute("inert"),
    );
    for (const el of behind) el.setAttribute("inert", "");
    stay.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void keep();
      if (e.key === "Tab" && box.current) {
        e.preventDefault();
        const buttons = [...box.current.querySelectorAll("button")];
        const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
        buttons[
          (at + (e.shiftKey ? -1 : 1) + buttons.length) % buttons.length
        ]?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      for (const el of behind) el.removeAttribute("inert");
      if (opener.current instanceof HTMLElement && opener.current.isConnected)
        opener.current.focus();
    };
  }, [open, keep]);

  if (left === null) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-text/40">
      <div
        ref={box}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="idle-title"
        aria-describedby="idle-text"
        className="w-96 rounded border border-border bg-surface p-6 shadow-menu"
      >
        <h2 id="idle-title" className="text-lg font-semibold">
          You will be signed out soon
        </h2>
        <p id="idle-text" className="mt-2">
          You have been inactive. For your security you will be signed out in{" "}
          {String(left)} {left === 1 ? "second" : "seconds"}.
        </p>
        {/* Announced at 60, 30 and 10 seconds only, not every second. */}
        <p className="sr-only" aria-live="assertive" aria-atomic="true">
          {said}
        </p>
        <div className="mt-4 flex gap-3">
          <button
            ref={stay}
            type="button"
            onClick={() => {
              void keep();
            }}
            className="rounded bg-accent px-3 py-1 text-accent-contrast"
          >
            Stay signed in
          </button>
          <button
            type="button"
            onClick={() => {
              signOut();
            }}
            className="rounded border border-border px-3 py-1"
          >
            Sign out now
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
