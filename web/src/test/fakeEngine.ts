/** A stand-in for the MapLibre engine in component tests: it records what the page asks for. */
import type { Colours, Engine, Handlers } from "@/features/map/engine";
import type { Step } from "@/features/map/scale";

export const engines: FakeEngine[] = [];

export class FakeEngine implements Engine {
  steps = new Map<string, Step>();
  selected: string | null = null;
  colours: Colours;
  destroyed = false;
  constructor(
    readonly container: HTMLElement,
    colours: Colours,
    readonly on: Handlers,
  ) {
    this.colours = colours;
  }
  setSteps(steps: ReadonlyMap<string, Step>) {
    this.steps = new Map(steps);
  }
  setSelected(code: string | null) {
    this.selected = code;
  }
  setColours(colours: Colours) {
    this.colours = colours;
  }
  destroy() {
    this.destroyed = true;
  }
}

export function createEngine(
  container: HTMLElement,
  colours: Colours,
  on: Handlers,
): Engine {
  const engine = new FakeEngine(container, colours, on);
  engines.push(engine);
  return engine;
}
