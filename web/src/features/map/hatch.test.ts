import { describe, expect, it } from "vitest";

import { hatch, SIZE } from "./hatch";

const inked = (step: number, fill: string) => {
  const { data } = hatch(step, fill);
  const out: number[] = [];
  for (let i = 0; i < data.length; i += 4)
    if (data[i + 3] === 255) out.push(i / 4);
  return {
    pixels: out,
    colour: out.length ? data[(out[0] ?? 0) * 4] : undefined,
  };
};

describe("hatch patterns", () => {
  it("draws nothing for step 0 and a different pattern for every other step", () => {
    expect(inked(0, "#000000").pixels).toEqual([]);
    const shapes = [1, 2, 3, 4].map((s) =>
      inked(s, "#7a7a7a").pixels.join(","),
    );
    expect(new Set(shapes).size).toBe(4);
    expect(hatch(1, "#000000").data).toHaveLength(SIZE * SIZE * 4);
  });

  it("draws lines that contrast with the fill", () => {
    expect(inked(4, "#ffffff").colour).toBe(0);
    expect(inked(1, "#3d3d3d").colour).toBe(255);
  });
});
