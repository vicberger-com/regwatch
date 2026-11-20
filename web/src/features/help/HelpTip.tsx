import { Link } from "@tanstack/react-router";
import { Info } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { topic as findTopic } from "./topics";

/**
 * The two-layer help for a setting (owner request, 2026-11-20): an ⓘ button whose tip says in
 * one or two sentences what the element is or does, with a "Learn more" link to its section
 * of the help page. It follows the toggletip pattern (WCAG 1.4.13): it opens on hover, on
 * keyboard focus and on click; it stays open while the pointer is over it, so the link can be
 * reached; Escape closes it; its text is announced when it opens.
 */
export function HelpTip({ id }: { id: string }) {
  const topic = findTopic(id);
  const [open, setOpen] = useState(false);
  const tipId = useId();
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onPointer = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  if (!topic) return null;
  return (
    <span ref={box} className="group relative inline-flex align-middle">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={tipId}
        // Focus opens it (a click focuses first); Escape, a click elsewhere, or focus leaving
        // the button and its tip close it.
        onClick={() => {
          setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
        }}
        onBlur={(e) => {
          if (!box.current?.contains(e.relatedTarget)) setOpen(false);
        }}
        className="rounded-full p-0.5 text-text-muted hover:text-accent"
      >
        <Info aria-hidden="true" className="h-4 w-4" />
        <span className="sr-only">About {topic.title}</span>
      </button>
      {/* Shown while open, or while the pointer is over the button or the tip itself. */}
      <span
        id={tipId}
        aria-live="polite"
        className={`absolute left-0 top-full z-30 mt-1 w-72 rounded border border-border bg-surface p-3 text-sm font-normal text-text shadow-menu ${
          open ? "block" : "hidden group-hover:block"
        }`}
      >
        <span className="block">{topic.tip}</span>
        <Link
          onBlur={(e) => {
            if (!box.current?.contains(e.relatedTarget)) setOpen(false);
          }}
          to="/help"
          hash={topic.id}
          className="mt-2 inline-block text-accent underline"
          onClick={() => {
            setOpen(false);
          }}
        >
          Learn more about {topic.title}
        </Link>
      </span>
    </span>
  );
}
