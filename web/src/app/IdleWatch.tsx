import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { preferencesQuery } from "@/features/me/api";
import { api } from "@/lib/api/client";
import { useLogout } from "@/lib/auth/session";

const WARNING_S = 60;
const ACTIVITY = ["keydown", "pointerdown", "wheel", "touchstart"] as const;

/**
 * M9 acceptance 2: after the idle timeout in force less 60 seconds without input, a dialog
 * warns that the session will end, counts down in a live region, and signs out at zero. "Stay
 * signed in" asks the API once, which renews the session's last activity. The API enforces the
 * timeout on its own; this only makes it visible.
 */
export function IdleWatch() {
  const prefs = useQuery(preferencesQuery);
  const minutes = prefs.data?.session_idle_timeout_minutes ?? 480;
  const logout = useLogout();
  const navigate = useNavigate();
  const last = useRef(0); // set when the watch starts
  const [left, setLeft] = useState<number | null>(null); // seconds, while warning
  const stay = useRef<HTMLButtonElement>(null);

  const signOut = useCallback(() => {
    logout.mutate(undefined, {
      onSettled: () => {
        void navigate({ to: "/login", search: {} });
      },
    });
  }, [logout, navigate]);

  useEffect(() => {
    if (last.current === 0) last.current = Date.now();
    const touch = () => {
      if (left === null) last.current = Date.now();
    };
    for (const name of ACTIVITY)
      window.addEventListener(name, touch, { passive: true });
    const tick = window.setInterval(() => {
      const idle = (Date.now() - last.current) / 1000;
      const remaining = Math.ceil(minutes * 60 - idle);
      if (remaining <= 0) {
        window.clearInterval(tick);
        signOut();
      } else if (remaining <= WARNING_S) {
        setLeft(remaining);
      }
    }, 1000);
    return () => {
      for (const name of ACTIVITY) window.removeEventListener(name, touch);
      window.clearInterval(tick);
    };
  }, [minutes, left, signOut]);

  useEffect(() => {
    if (left !== null) stay.current?.focus();
  }, [left !== null]); // eslint-disable-line react-hooks/exhaustive-deps -- focus once, on opening

  const keep = useCallback(() => {
    last.current = Date.now();
    setLeft(null);
    void api.GET("/auth/me"); // renews last activity on the server
  }, []);
  // While the warning shows: Escape keeps the session, Tab stays on the two buttons.
  const box = useRef<HTMLDivElement>(null);
  const open = left !== null;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") keep();
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
    };
  }, [open, keep]);

  if (left === null) return null;
  return (
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
          <span aria-live="assertive" aria-atomic="true">
            {String(left)} {left === 1 ? "second" : "seconds"}
          </span>
          .
        </p>
        <div className="mt-4 flex gap-3">
          <button
            ref={stay}
            type="button"
            onClick={keep}
            className="rounded bg-accent px-3 py-1 text-accent-contrast"
          >
            Stay signed in
          </button>
          <button
            type="button"
            onClick={signOut}
            className="rounded border border-border px-3 py-1"
          >
            Sign out now
          </button>
        </div>
      </div>
    </div>
  );
}
