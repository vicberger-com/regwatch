/**
 * A unified diff of plain text (`GET /items/{id}/diff`), shown line by line with a text marker
 * as well as colour, so the change does not depend on colour alone (WCAG 1.4.1). Every line is
 * a text node; captured text never becomes markup.
 */
export interface DiffLine {
  kind: "add" | "remove" | "context" | "hunk";
  text: string;
}

export function parseDiff(unified: string): DiffLine[] {
  const out: DiffLine[] = [];
  for (const line of unified.split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) continue; // file headers
    if (line.startsWith("@@")) out.push({ kind: "hunk", text: line });
    else if (line.startsWith("+"))
      out.push({ kind: "add", text: line.slice(1) });
    else if (line.startsWith("-"))
      out.push({ kind: "remove", text: line.slice(1) });
    else if (line || out.length)
      out.push({
        kind: "context",
        text: line.startsWith(" ") ? line.slice(1) : line,
      });
  }
  while (out.at(-1)?.kind === "context" && out.at(-1)?.text === "") out.pop();
  return out;
}

const STYLE: Record<
  DiffLine["kind"],
  { marker: string; label: string; className: string }
> = {
  add: { marker: "+", label: "Added", className: "bg-good/15" },
  remove: {
    marker: "−",
    label: "Removed",
    className: "bg-critical/15 line-through decoration-critical/60",
  },
  context: { marker: " ", label: "", className: "" },
  hunk: { marker: "", label: "", className: "text-text-muted" },
};

export function DiffView({
  unified,
  label,
}: {
  unified: string;
  label: string;
}) {
  const lines = parseDiff(unified);
  if (lines.length === 0)
    return (
      <p className="text-text-muted">No changes between these versions.</p>
    );
  const added = lines.filter((l) => l.kind === "add").length;
  const removed = lines.filter((l) => l.kind === "remove").length;
  return (
    <figure>
      <figcaption className="mb-2 text-sm text-text-muted">
        {label}: {String(added)} lines added, {String(removed)} removed
      </figcaption>
      <ol className="overflow-x-auto rounded border border-border bg-surface font-mono text-sm">
        {lines.map((line, i) => {
          const style = STYLE[line.kind];
          return (
            <li
              key={i}
              className={`flex whitespace-pre-wrap px-2 ${style.className}`}
            >
              <span aria-hidden="true" className="w-4 shrink-0 select-none">
                {style.marker}
              </span>
              {style.label && <span className="sr-only">{style.label}: </span>}
              <span>{line.text || " "}</span>
            </li>
          );
        })}
      </ol>
    </figure>
  );
}
