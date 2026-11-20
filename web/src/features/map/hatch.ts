/**
 * Hatch patterns for the high-contrast theme (ADR-0004 decision 7, WCAG 1.4.1): each colour
 * step also gets its own line pattern, so steps differ without colour. Built as raw RGBA so
 * no canvas is needed; lines are black or white, whichever contrasts with the step's fill.
 */
export const SIZE = 12;

type Pattern = (x: number, y: number) => boolean;

const PATTERNS: Pattern[] = [
  () => false, // step 0: no change, no lines
  (x, y) => (x + y) % 12 === 0, // sparse diagonal
  (x, y) => (x - y + 12) % 6 === 0, // anti-diagonal
  (x, y) => (x + y) % 6 === 0 || (x - y + 12) % 6 === 0, // cross-hatch
  (x, y) => (x + y) % 4 === 0, // dense diagonal
];

function luminance(hex: string): number {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m?.[1]) return 0;
  const n = Number.parseInt(m[1], 16);
  return (
    (0.2126 * ((n >> 16) & 255) +
      0.7152 * ((n >> 8) & 255) +
      0.0722 * (n & 255)) /
    255
  );
}

/** The pattern image of ``step`` drawn over ``fill`` (a #rrggbb colour). */
export function hatch(
  step: number,
  fill: string,
): { width: number; height: number; data: Uint8Array } {
  const data = new Uint8Array(SIZE * SIZE * 4);
  const line = luminance(fill) > 0.5 ? 0 : 255;
  const draw = PATTERNS[step] ?? PATTERNS[0];
  for (let y = 0; y < SIZE; y++) {
    for (let x = 0; x < SIZE; x++) {
      if (draw?.(x, y)) {
        const i = (y * SIZE + x) * 4;
        data[i] = line;
        data[i + 1] = line;
        data[i + 2] = line;
        data[i + 3] = 255;
      }
    }
  }
  return { width: SIZE, height: SIZE, data };
}
