import { afterEach, describe, expect, it } from "vitest";

import { applyAppearance, readStoredAppearance, resolve } from "./appearance";

afterEach(() => {
  const root = document.documentElement;
  root.removeAttribute("style");
  for (const name of ["theme", "motion", "labels", "hit"])
    root.removeAttribute(`data-${name}`);
});

describe("appearance", () => {
  it("follows the system theme until one is chosen", () => {
    expect(resolve({ theme: "system" }, true).theme).toBe("dark");
    expect(resolve(undefined, false).theme).toBe("light");
    expect(resolve({ theme: "high-contrast" }, false).theme).toBe(
      "high-contrast",
    );
  });

  it("lets the accessibility preset fill in what the user left at default", () => {
    const preset = resolve({ accessibility_preset: true }, false);
    expect(preset).toEqual({
      theme: "high-contrast",
      fontScale: 1.25,
      density: 1,
      motion: "reduce",
      labels: "always",
      largeTargets: true,
    });
    const own = resolve(
      {
        accessibility_preset: true,
        theme: "dark",
        font_scale: 150,
        reduced_motion: "off",
      },
      false,
    );
    expect([own.theme, own.fontScale, own.motion]).toEqual([
      "dark",
      1.5,
      "full",
    ]);
  });

  it("applies to <html> and survives a reload through the stored copy", () => {
    applyAppearance(
      resolve(
        {
          font_scale: 175,
          density: "compact",
          reduced_motion: "on",
          theme: "dark",
        },
        false,
      ),
    );
    const root = document.documentElement;
    expect(root.dataset.theme).toBe("dark");
    expect(root.style.getPropertyValue("--font-scale")).toBe("1.75");
    expect(root.style.getPropertyValue("--density")).toBe("0.85");
    expect(root.dataset.motion).toBe("reduce");
    expect(readStoredAppearance()).toMatchObject({
      theme: "dark",
      fontScale: 1.75,
    });
  });

  it("ignores a tampered stored copy", () => {
    localStorage.setItem(
      "regwatch.appearance",
      JSON.stringify({ theme: "<x>", fontScale: 1 }),
    );
    expect(readStoredAppearance()).toBeNull();
    localStorage.setItem(
      "regwatch.appearance",
      JSON.stringify({ theme: "dark", fontScale: 99, density: -1 }),
    );
    expect(readStoredAppearance()).toMatchObject({
      fontScale: 2,
      density: 0.85,
    });
    localStorage.setItem("regwatch.appearance", "{not json");
    expect(readStoredAppearance()).toBeNull();
  });
});
