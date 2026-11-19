// Project GeoJSON lng/lat to Equal Earth (Šavrič, Patterson and Jenny 2018), scaled so the
// world fits MapLibre's pre-registered `identity` projection, whose tile 0/0/0 spans -90..90 on
// both axes (ADR-0004 amendment 1). Usage: node project-equal-earth.mjs in.geojson out.geojson
import { readFileSync, writeFileSync } from "node:fs";

const A1 = 1.340264, A2 = -0.081106, A3 = 0.000893, A4 = 0.003796;
const M = Math.sqrt(3) / 2;
const XMAX = 2.7066297319215575; // x at lng 180, lat 0 on the unit sphere
export const SCALE = 90 / XMAX; // the world's width fills -90..90

export function equalEarth([lng, lat]) {
  const l = (lng * Math.PI) / 180;
  const p = Math.asin(M * Math.sin((lat * Math.PI) / 180));
  const p2 = p * p, p6 = p2 * p2 * p2;
  const x = (l * Math.cos(p)) / (M * (A1 + 3 * A2 * p2 + p6 * (7 * A3 + 9 * A4 * p2)));
  const y = p * (A1 + A2 * p2 + p6 * (A3 + A4 * p2));
  return [Math.round(x * SCALE * 1e3) / 1e3, Math.round(y * SCALE * 1e3) / 1e3];
}

function walk(coords) {
  return typeof coords[0] === "number" ? equalEarth(coords) : coords.map(walk);
}

const [, , source, target] = process.argv;
if (source && target) {
  const data = JSON.parse(readFileSync(source, "utf8"));
  for (const feature of data.features) feature.geometry.coordinates = walk(feature.geometry.coordinates);
  writeFileSync(target, JSON.stringify(data));
}
