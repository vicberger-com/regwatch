import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

/**
 * Tabs (WAI-ARIA APG, automatic activation): arrow keys, Home and End move between tabs and
 * show their panel; only the active tab is in the tab order.
 */
export function Tabs(props: {
  label: string;
  tabs: { id: string; label: string; panel: () => ReactNode }[];
  active: string;
  onChange: (id: string) => void;
}) {
  const base = useId();
  const list = useRef<HTMLDivElement>(null);
  const index = Math.max(
    0,
    props.tabs.findIndex((t) => t.id === props.active),
  );
  const go = (to: number) => {
    const count = props.tabs.length;
    const next = props.tabs[(to + count) % count];
    if (!next) return;
    props.onChange(next.id);
    list.current
      ?.querySelector<HTMLElement>(`#${CSS.escape(`${base}-tab-${next.id}`)}`)
      ?.focus();
  };
  const onKey = (e: KeyboardEvent) => {
    const moves: Partial<Record<string, number>> = {
      ArrowRight: index + 1,
      ArrowLeft: index - 1,
      Home: 0,
      End: props.tabs.length - 1,
    };
    const to = moves[e.key];
    if (to !== undefined) {
      e.preventDefault();
      go(to);
    }
  };
  const current = props.tabs[index];
  return (
    <div>
      <div
        ref={list}
        role="tablist"
        aria-label={props.label}
        className="flex gap-1 border-b border-border"
      >
        {props.tabs.map((tab) => {
          const selected = tab.id === current?.id;
          return (
            <button
              key={tab.id}
              id={`${base}-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`${base}-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              onKeyDown={onKey}
              onClick={() => {
                props.onChange(tab.id);
              }}
              className={`-mb-px border-b-2 px-3 py-2 ${selected ? "border-accent font-semibold" : "border-transparent text-text-muted"}`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      {current && (
        <div
          id={`${base}-panel-${current.id}`}
          role="tabpanel"
          aria-labelledby={`${base}-tab-${current.id}`}
          className="pt-4"
        >
          {current.panel()}
        </div>
      )}
    </div>
  );
}
