import { Fragment } from "react";

/**
 * A highlight from `POST /search`: escaped text with `<mark>` around matched words (M5). It is
 * never given to innerHTML: the string is split on the two tags, the five entities Python's
 * `html.escape` writes are decoded, and every piece becomes a text node.
 */
const ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#x27;": "'",
};

export function decode(text: string): string {
  return text.replace(/&(?:amp|lt|gt|quot|#x27);/g, (e) => ENTITIES[e] ?? e);
}

export function segments(marked: string): { text: string; mark: boolean }[] {
  const out: { text: string; mark: boolean }[] = [];
  for (const [i, part] of marked.split(/<mark>|<\/mark>/).entries()) {
    if (part) out.push({ text: decode(part), mark: i % 2 === 1 });
  }
  return out;
}

export function Marked({ html }: { html: string }) {
  return (
    <>
      {segments(html).map((s, i) =>
        s.mark ? (
          <mark key={i} className="rounded-sm bg-warning/30 text-text">
            {s.text}
          </mark>
        ) : (
          <Fragment key={i}>{s.text}</Fragment>
        ),
      )}
    </>
  );
}
