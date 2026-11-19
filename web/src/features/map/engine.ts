/**
 * MapLibre, loaded on the map route only (bundle budget; ADR-0004). The boundaries are
 * pre-projected to Equal Earth at build time and drawn in MapLibre's `identity` projection
 * (ADR-0004 amendment 1), so no projection script in the workers and no experimental CRS. No basemap,
 * no tiles and no network beyond the two same-origin GeoJSON files.
 */
import {
  Map as MapLibreMap,
  setWorkerUrl,
  type MapLayerMouseEvent,
  type MapMouseEvent,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

import type { Step } from "./scale";

export interface Engine {
  setSteps(steps: ReadonlyMap<string, Step>): void;
  setSelected(code: string | null): void;
  setColours(colours: Colours): void;
  destroy(): void;
}

export interface Colours {
  steps: [string, string, string, string, string];
  border: string;
  selected: string;
  disputed: string;
}

export interface Handlers {
  onSelect(code: string): void;
  onHover(
    hit: {
      code: string;
      name: string;
      x: number;
      y: number;
      note?: string;
    } | null,
  ): void;
}

const fill = (c: Colours): unknown => [
  "match",
  ["coalesce", ["feature-state", "step"], 0],
  1, c.steps[1], 2, c.steps[2], 3, c.steps[3], 4, c.steps[4],
  c.steps[0],
]; // prettier-ignore

// The pre-projected world (scripts/project-equal-earth.mjs): x within ±90, y within ±44.
const WORLD: [[number, number], [number, number]] = [
  [-90, -45],
  [90, 45],
];

// The worker is a same-origin file emitted by the build (CSP worker-src 'self'; no blob URL).
setWorkerUrl(workerUrl);

export function createEngine(
  container: HTMLElement,
  colours: Colours,
  on: Handlers,
): Engine {
  const map = new MapLibreMap({
    container,
    style: {
      version: 8,
      projection: { type: "identity" },
      sources: {
        countries: { type: "geojson", data: "/map/countries.geojson", promoteId: "iso" },
        disputed: { type: "geojson", data: "/map/disputed.geojson" },
      },
      layers: [
        { id: "background", type: "background", paint: { "background-color": "rgba(0,0,0,0)" } },
        { id: "fill", type: "fill", source: "countries", paint: { "fill-color": fill(colours) as never } },
        { id: "border", type: "line", source: "countries", paint: { "line-color": colours.border, "line-width": 0.5 } },
        { id: "selected", type: "line", source: "countries", filter: ["==", ["get", "iso"], ""], paint: { "line-color": colours.selected, "line-width": 2 } },
        { id: "disputed", type: "fill", source: "disputed", paint: { "fill-color": colours.disputed } },
        { id: "disputed-line", type: "line", source: "disputed", paint: { "line-color": colours.border, "line-dasharray": [2, 2] } },
      ],
    },
    attributionControl: false,
    keyboard: false, // keyboard users work through the jurisdiction listbox (screens.md)
    dragRotate: false,
    renderWorldCopies: false,
  }); // prettier-ignore
  map.getCanvas().removeAttribute("tabindex");
  map.getCanvas().setAttribute("aria-hidden", "true");

  let current = new Map<string, Step>();
  let selected: string | null = null;
  let palette = colours;
  let ready = false;
  const apply = () => {
    if (!ready) return;
    map.removeFeatureState({ source: "countries" });
    for (const [code, value] of current)
      map.setFeatureState({ source: "countries", id: code }, { step: value });
    map.setFilter("selected", ["==", ["get", "iso"], selected ?? ""]);
    map.setPaintProperty("fill", "fill-color", fill(palette) as never);
    map.setPaintProperty("border", "line-color", palette.border);
    map.setPaintProperty("disputed", "fill-color", palette.disputed);
    map.setPaintProperty("disputed-line", "line-color", palette.border);
    map.setPaintProperty("selected", "line-color", palette.selected);
  };
  const fit = () => {
    map.fitBounds(WORLD, { padding: 8, animate: false });
  };
  map.on("load", () => {
    ready = true;
    fit();
    apply();
  });
  map.on("resize", fit); // until then, changes are kept and applied on load
  map.on("click", "fill", (e: MapLayerMouseEvent) => {
    // A disputed area drawn on top is nobody's to select (ADR-0004 decision 5).
    if (map.queryRenderedFeatures(e.point, { layers: ["disputed"] }).length > 0)
      return;
    const iso = e.features?.[0]?.properties.iso as string | undefined;
    if (iso && /^[A-Z]{2}$/.test(iso)) on.onSelect(iso);
  });
  map.on("mousemove", (e: MapMouseEvent) => {
    const [hit] = map.queryRenderedFeatures(e.point, { layers: ["disputed", "fill"] });
    const props = hit?.properties as { iso?: string; name?: string; note?: string } | undefined;
    on.onHover(props?.name ? { code: props.iso ?? "", name: props.name, x: e.point.x, y: e.point.y, ...(props.note ? { note: props.note } : {}) } : null);
  }); // prettier-ignore
  map.on("mouseout", () => {
    on.onHover(null);
  });

  return {
    setSteps(steps) {
      current = new Map(steps);
      apply();
    },
    setSelected(code) {
      selected = code;
      apply();
    },
    setColours(c) {
      palette = c;
      apply();
    },
    destroy() {
      map.remove();
    },
  };
}
