import { useId, useRef, useState, type KeyboardEvent } from "react";

export interface ListEntry {
  code: string;
  name: string;
  summary: string;
}

/**
 * The map's keyboard and screen-reader equivalent (screens.md): a listbox of the jurisdictions
 * with changes, newest first; arrow keys move, Enter or Space selects, and selection syncs with
 * the map.
 */
export function JurisdictionList(props: {
  label: string;
  entries: readonly ListEntry[];
  selected: string | null;
  onSelect: (code: string) => void;
}) {
  const id = useId();
  const list = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const { entries } = props;
  const at = Math.min(active, Math.max(0, entries.length - 1));
  // A selection made on the map moves the active option too (state adjusted during render,
  // as React recommends over an effect).
  const [seen, setSeen] = useState(props.selected);
  if (props.selected !== seen) {
    setSeen(props.selected);
    const index = entries.findIndex((e) => e.code === props.selected);
    if (index >= 0) setActive(index);
  }

  const move = (to: number) => {
    const next = Math.min(entries.length - 1, Math.max(0, to));
    setActive(next);
    const option = list.current?.querySelector(
      `#${CSS.escape(`${id}-${String(next)}`)}`,
    );
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- absent in jsdom
    option?.scrollIntoView?.({ block: "nearest" });
  };
  const onKey = (e: KeyboardEvent) => {
    const choose = () => {
      const entry = entries[at];
      if (entry) props.onSelect(entry.code);
    };
    const keys: Partial<Record<string, () => void>> = {
      ArrowDown: () => {
        move(at + 1);
      },
      ArrowUp: () => {
        move(at - 1);
      },
      Home: () => {
        move(0);
      },
      End: () => {
        move(entries.length - 1);
      },
      Enter: choose,
      " ": choose,
    };
    const run = keys[e.key];
    if (run) {
      e.preventDefault();
      run();
    }
  };

  if (entries.length === 0) {
    return (
      <p className="text-text-muted">
        No jurisdiction has changes in this period.
      </p>
    );
  }
  return (
    <div
      ref={list}
      role="listbox"
      tabIndex={0}
      aria-label={props.label}
      aria-activedescendant={`${id}-${String(at)}`}
      onKeyDown={onKey}
      className="group max-h-[60vh] overflow-y-auto rounded border border-border bg-surface"
    >
      {entries.map((entry, i) => (
        // The listbox pattern with aria-activedescendant: the list holds focus and the keys, and
        // options are not focusable themselves (WAI-ARIA APG listbox).
        // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/interactive-supports-focus
        <div
          key={entry.code}
          id={`${id}-${String(i)}`}
          role="option"
          aria-selected={entry.code === props.selected}
          onClick={() => {
            setActive(i);
            props.onSelect(entry.code);
          }}
          className={`cursor-pointer border-b border-border px-3 py-2 last:border-b-0 ${
            i === at
              ? "group-focus:outline group-focus:outline-2 group-focus:-outline-offset-2 group-focus:outline-focus"
              : ""
          } ${entry.code === props.selected ? "bg-bg font-semibold" : ""}`}
        >
          <span className="block">{entry.name}</span>
          <span className="block text-sm text-text-muted">{entry.summary}</span>
        </div>
      ))}
    </div>
  );
}
