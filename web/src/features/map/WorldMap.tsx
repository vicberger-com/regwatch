import { useEffect, useRef, useState } from "react";

import type { Colours, Engine } from "./engine";
import type { Step } from "./scale";

function cssVar(name: string): string {
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    "#888888"
  );
}

function readColours(): Colours {
  return {
    steps: [0, 1, 2, 3, 4].map((i) =>
      cssVar(`--map-${String(i)}`),
    ) as Colours["steps"],
    border: cssVar("--border"),
    selected: cssVar("--focus"),
    disputed: cssVar("--map-0"),
    patterns: document.documentElement.dataset.theme === "high-contrast",
  };
}

interface Hover {
  disputed?: boolean;
  code: string;
  name: string;
  x: number;
  y: number;
  note?: string;
}

/**
 * The choropleth (M6). Pointer users hover and click; everyone else uses the jurisdiction list,
 * which shows the same data, so the canvas is hidden from assistive technology.
 */
export function WorldMap(props: {
  label: string;
  steps: ReadonlyMap<string, Step>;
  selected: string | null;
  onSelect: (code: string) => void;
  describe: (code: string) => string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const engine = useRef<Engine | null>(null);
  const select = useRef(props.onSelect);
  useEffect(() => {
    select.current = props.onSelect;
  }, [props.onSelect]);
  const [hover, setHover] = useState<Hover | null>(null);
  const [failed, setFailed] = useState(false);
  const { steps, selected } = props;
  const latest = useRef({ steps, selected });
  useEffect(() => {
    latest.current = { steps, selected };
  }, [steps, selected]);

  useEffect(() => {
    let alive = true;
    const container = box.current;
    if (!container) return;
    import("./engine")
      .then(({ createEngine }) => {
        if (!alive) return;
        engine.current = createEngine(container, readColours(), {
          onSelect: (code) => {
            select.current(code);
          },
          onHover: setHover,
        });
        // Data that arrived before the engine (lazy-loaded) is applied now (use testing U-M6-2).
        engine.current.setSteps(latest.current.steps);
        engine.current.setSelected(latest.current.selected);
      })
      .catch(() => {
        if (alive) setFailed(true); // no WebGL: the list still has everything
      });
    // Themes change data-theme on <html>: recolour from the tokens.
    const watch = new MutationObserver(() =>
      engine.current?.setColours(readColours()),
    );
    watch.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "style"],
    });
    return () => {
      alive = false;
      watch.disconnect();
      engine.current?.destroy();
      engine.current = null;
    };
  }, []);

  useEffect(() => {
    engine.current?.setSteps(steps);
  }, [steps]);
  useEffect(() => {
    engine.current?.setSelected(selected);
  }, [selected]);

  return (
    <div
      role="region"
      aria-label={props.label}
      className="relative h-[60vh] min-h-80 rounded border border-border bg-surface"
    >
      {/* Full size, not absolute: maplibre-gl.css makes the map element position: relative,
          which would leave an absolutely placed box 0 px high (use testing U-M6-1). */}
      <div ref={box} className="h-full w-full" />
      {failed && (
        <p className="absolute inset-0 flex items-center justify-center p-4 text-text-muted">
          The map cannot be drawn in this browser; the list beside it has the
          same information.
        </p>
      )}
      {hover && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute z-10 max-w-64 rounded border border-border bg-surface px-2 py-1 text-sm shadow-menu"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
        >
          {hover.disputed ? (
            <>
              {/* No country is named over a disputed area (ADR-0004 decision 5). */}
              <span className="font-semibold">Disputed area</span>
              {hover.note && (
                <span className="block text-text-muted">{hover.note}</span>
              )}
            </>
          ) : (
            <>
              <span className="font-semibold">{hover.name}</span>
              <span className="block text-text-muted">
                {props.describe(hover.code)}
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
