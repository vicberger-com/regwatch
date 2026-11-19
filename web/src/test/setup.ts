import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom has no WebGL: the map engine is replaced by a recorder (src/features/map/engine.ts).
vi.mock("@/features/map/engine", () => import("./fakeEngine"));

afterEach(() => {
  cleanup();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});
