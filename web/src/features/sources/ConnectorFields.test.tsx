import { describe, expect, it } from "vitest";

import {
  fromForm,
  KINDS,
  kindSchema,
  mergeConfig,
  SUPPORTED_TYPES,
  toForm,
} from "./ConnectorFields";

describe("connector form values", () => {
  const rss = kindSchema("rss");
  const crawl = kindSchema("web_crawl");

  it("shows stored lists one per line and sends them back as lists", () => {
    if (!crawl) throw new Error("no web_crawl schema");
    const form = toForm(crawl, {
      seed_urls: ["https://a.example/", "https://b.example/"],
    });
    expect(form.seed_urls).toBe("https://a.example/\nhttps://b.example/");
    expect(
      fromForm(crawl, {
        ...form,
        allowed_domains: " a.example \n\n b.example ",
      }),
    ).toMatchObject({
      seed_urls: ["https://a.example/", "https://b.example/"],
      allowed_domains: ["a.example", "b.example"],
      max_depth: 3,
    });
  });

  it("leaves empty fields out and keeps numbers as numbers", () => {
    if (!rss) throw new Error("no rss schema");
    expect(
      fromForm(rss, {
        feed_url: " ",
        max_entries: "12",
        fetch_full_page: false,
      }),
    ).toEqual({
      max_entries: 12,
      fetch_full_page: false,
      etag_conditional: false,
    });
    expect(fromForm(rss, { max_entries: "many" })).toMatchObject({
      max_entries: "many",
    });
    expect(kindSchema("nope")).toBeNull();
  });

  it("supports every field type the contract uses", () => {
    for (const kind of KINDS) {
      const schema = kindSchema(kind);
      if (!schema) throw new Error(kind);
      for (const [name, prop] of Object.entries(schema.properties)) {
        expect(SUPPORTED_TYPES.has(prop.type ?? ""), `${kind}.${name}`).toBe(
          true,
        );
        if (prop.type === "array")
          expect(prop.items?.type, `${kind}.${name}`).toBe("string");
      }
    }
  });

  it("merges the form over the stored config", () => {
    const api = kindSchema("api_feed");
    if (!api) throw new Error("no api_feed schema");
    const stored = {
      provider: "eur_lex",
      params: { a: 1 },
      unknown_key: "kept",
    };
    const form = { ...toForm(api, stored), item_path: "$.x" };
    expect(mergeConfig(api, stored, form)).toEqual({
      provider: "eur_lex",
      params: { a: 1 },
      unknown_key: "kept",
      item_path: "$.x",
    });
  });
});
