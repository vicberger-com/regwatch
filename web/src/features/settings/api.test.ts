import { describe, expect, it } from "vitest";

import { groupByPrefix, parseValue, toText, type Setting } from "./api";

const SETTINGS: Setting[] = ["auth.a", "auth.b", "map.c", "general.d"].map(
  (key) => ({
    key,
    type: "string",
    value: "",
  }),
);

function setting(type: string, extra: Partial<Setting> = {}): Setting {
  return { key: "x.y", type, value: null, ...extra };
}

describe("setting values", () => {
  it("parses each type and refuses what does not fit", () => {
    expect(parseValue(setting("integer"), "42")).toEqual({ value: 42 });
    expect(parseValue(setting("integer"), "4.2")).toHaveProperty("error");
    expect(
      parseValue(setting("integer"), "99999999999999999999"),
    ).toHaveProperty("error");
    expect(parseValue(setting("number"), "0.5")).toEqual({ value: 0.5 });
    expect(parseValue(setting("number"), "-1")).toHaveProperty("error");
    expect(parseValue(setting("number"), "")).toHaveProperty("error");
    expect(parseValue(setting("boolean"), "true")).toEqual({ value: true });
    expect(parseValue(setting("enum", { values: ["a"] }), "b")).toHaveProperty(
      "error",
    );
    expect(parseValue(setting("list"), " a.org \n\n b.org ")).toEqual({
      value: ["a.org", "b.org"],
    });
    expect(parseValue(setting("string"), " t ")).toEqual({ value: " t " });
  });

  it("shows values as text and groups keys by prefix", () => {
    expect(toText(setting("list", { value: ["a", "b"] }))).toBe("a\nb");
    expect(toText(setting("string", { value: { odd: true } }))).toBe("");
    expect(groupByPrefix(SETTINGS).map(([p, s]) => [p, s.length])).toEqual([
      ["auth", 2],
      ["general", 1],
      ["map", 1],
    ]);
  });
});
