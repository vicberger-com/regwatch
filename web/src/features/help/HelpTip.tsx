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
  const [open, setOpen] = useState(false); // by focus or click
  const [hover, setHover] = useState(false); // by the pointer over the button or the tip
  const shown = open || hover;
  const justFocused = useRef(false);
  const tipId = useId();
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!shown) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation(); // this tip's Escape only (listener runs first: capture)
      setOpen(false);
      setHover(false); // hidden until the pointer leaves and returns (WCAG 1.4.13 dismissible)
    };
    const onPointer = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [shown]);

  if (!topic) return null;
  const leaveFocus = (next: EventTarget | null) => {
    if (!box.current?.contains(next as Node | null)) setOpen(false);
  };
  return (
    <span
      ref={box}
      className="relative inline-flex align-middle"
      onPointerEnter={() => {
        setHover(true);
      }}
      onPointerLeave={() => {
        setHover(false);
      }}
    >
      <button
        type="button"
        aria-expanded={shown}
        aria-controls={tipId}
        // Focus opens it; a click toggles it (the click that focused it keeps it open);
        // Escape, a press elsewhere, or focus leaving the button and its tip close it.
        onFocus={() => {
          justFocused.current = true;
          setOpen(true);
        }}
        onClick={() => {
          if (justFocused.current) justFocused.current = false;
          else setOpen((o) => !o);
        }}
        onBlur={(e) => {
          justFocused.current = false;
          leaveFocus(e.relatedTarget);
        }}
        className="rounded-full p-0.5 text-text-muted hover:text-accent"
      >
        <Info aria-hidden="true" className="h-4 w-4" />
        <span className="sr-only">About {topic.title}</span>
      </button>
      {/* The live region is always displayed (empty while closed) and its text is added when
          the tip opens, so the tip is announced reliably. Padding, not margin, above the tip: no hover gap. */}
      <span
        id={tipId}
        aria-live="polite"
        className={`absolute left-0 top-full z-30 w-72 pt-1 ${shown ? "" : "pointer-events-none"}`}
      >
        {shown && (
          <span className="block rounded border border-border bg-surface p-3 text-sm font-normal text-text shadow-menu">
            <span className="block">{topic.tip}</span>
            <Link
              onBlur={(e) => {
                leaveFocus(e.relatedTarget);
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
        )}
      </span>
    </span>
  );
}
