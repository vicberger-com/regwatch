/**
 * A unified diff of plain text (`GET /items/{id}/diff`), shown line by line with a text marker
 * as well as colour, so the change does not depend on colour alone (WCAG 1.4.1). Every line is
 * a text node; captured text never becomes markup.
 */
export interface DiffLine {
  kind: "add" | "remove" | "context" | "hunk" | "cut";
  text: string;
}

/** The marker `processing/versioning.py` appends when it cuts a diff at 64 KB. */
export const CUT = "... (diff cut at 64 KB)";

/**
 * Lines of a `difflib.unified_diff`. The `---` and `+++` file headers come only before the
 * first hunk: after it, a line starting with `---` is a removed line that began with `--`, and
 * one starting with `+++` an added line that began with `++` (review finding 1: a page must not
 * hide a change by starting a line with dashes).
 */
export function parseDiff(unified: string): DiffLine[] {
  const out: DiffLine[] = [];
  let inHunks = false;
  for (const raw of unified.split("\n")) {
    const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
    if (line.startsWith("@@")) {
      inHunks = true;
      out.push({ kind: "hunk", text: line });
    } else if (!inHunks) {
      continue; // the file headers, and anything else before the first hunk
    } else if (line === CUT)
      out.push({ kind: "cut", text: "The diff was cut at 64 KB." });
    else if (line.startsWith("+"))
      out.push({ kind: "add", text: line.slice(1) });
    else if (line.startsWith("-"))
      out.push({ kind: "remove", text: line.slice(1) });
    else
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
  cut: {
    marker: "",
    label: "Notice",
    className: "font-sans italic text-warning",
  },
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
