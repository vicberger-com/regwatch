import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { decode, Marked, segments } from "./Marked";

describe("search highlights", () => {
  it("marks the matched words and decodes the escaped text", () => {
    expect(segments("NIS2 &amp; <mark>incident</mark> &lt;b&gt;")).toEqual([
      { text: "NIS2 & ", mark: false },
      { text: "incident", mark: true },
      { text: " <b>", mark: false },
    ]);
    expect(decode("&quot;a&#x27;s&quot;")).toBe('"a\'s"');
  });

  it("never turns captured text into markup", () => {
    const { container } = render(
      <Marked
        html={
          "&lt;img src=x onerror=alert(1)&gt;<mark>x</mark><script>bad()</script>"
        }
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelectorAll("mark")).toHaveLength(1);
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(container.textContent).toContain("<script>bad()</script>");
  });
});
