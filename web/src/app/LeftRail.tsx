import { Link, useRouteContext } from "@tanstack/react-router";
import { Pin, PinOff } from "lucide-react";
import { useState } from "react";

import { railCommands } from "./commands";

const PINNED_KEY = "regwatch.rail.pinned";

function readPinned(): boolean {
  try {
    return localStorage.getItem(PINNED_KEY) === "1";
  } catch {
    return false; // storage refused (private mode): unpinned
  }
}

/**
 * The left rail (screens.md layout grid): 64 px of icon links whose labels show on hover and
 * focus, or always when pinned (160 px). Every link keeps its label in the accessible name.
 */
export function LeftRail() {
  const { me } = useRouteContext({ from: "/authed" });
  const [pinned, setPinned] = useState(readPinned);
  const toggle = () => {
    const next = !pinned;
    setPinned(next);
    try {
      localStorage.setItem(PINNED_KEY, next ? "1" : "0");
    } catch {
      // not remembered; the choice still holds for this page
    }
  };

  return (
    <nav
      aria-label="Main"
      className={`flex shrink-0 flex-col gap-1 border-r border-border bg-surface py-2 ${
        pinned ? "w-40" : "w-16"
      }`}
    >
      {railCommands(me).map((command) => {
        const Icon = command.icon;
        const to = command.to ?? "/"; // railCommands keeps navigation commands only
        return (
          <Link
            key={command.id}
            to={to}
            activeOptions={{ exact: to === "/" }}
            activeProps={{
              "aria-current": "page",
              className: "bg-bg text-accent",
            }}
            className="group relative mx-2 flex h-10 items-center gap-3 rounded px-3 hover:bg-bg"
          >
            <Icon aria-hidden="true" className="h-5 w-5 shrink-0" />
            <span
              aria-hidden={pinned ? undefined : true}
              className={
                pinned
                  ? "truncate"
                  : "pointer-events-none absolute left-full z-10 ml-2 hidden whitespace-nowrap rounded border border-border bg-surface px-2 py-1 shadow-menu group-hover:block group-focus-visible:block"
              }
            >
              {command.label}
            </span>
            {!pinned && <span className="sr-only">{command.label}</span>}
          </Link>
        );
      })}
      <button
        type="button"
        aria-pressed={pinned}
        onClick={toggle}
        className="mx-2 mt-auto flex h-10 items-center gap-3 rounded px-3 text-text-muted hover:bg-bg"
      >
        {pinned ? (
          <PinOff aria-hidden="true" className="h-5 w-5 shrink-0" />
        ) : (
          <Pin aria-hidden="true" className="h-5 w-5 shrink-0" />
        )}
        <span className={pinned ? "truncate" : "sr-only"}>Show labels</span>
      </button>
    </nav>
  );
}
