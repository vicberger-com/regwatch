/**
 * The report component palette for the Puck editor (M7.4, ADR-0005). It mirrors the server's
 * nine prop schemas (`api/src/regwatch/reports/components.py`); the server validates every
 * save and renders the real report (M7.2), so the canvas shows labelled placeholders, not
 * data. No component takes HTML, a URL, a style or a class from the user.
 */
import type { Config } from "@puckeditor/core";
import type { ReactNode } from "react";

import type { ReportField } from "./api";

type Props = Record<string, unknown>;

function FieldChecks(props: {
  fields: ReportField[];
  value: unknown;
  onChange: (value: string[]) => void;
  max: number;
}) {
  const chosen = Array.isArray(props.value) ? (props.value as string[]) : [];
  return (
    <fieldset className="grid gap-1">
      <legend className="text-sm font-semibold">Columns</legend>
      {props.fields.map((f) => (
        <label key={f.key} className="flex min-h-6 items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-5 w-5 shrink-0"
            checked={chosen.includes(f.key ?? "")}
            disabled={
              !chosen.includes(f.key ?? "") && chosen.length >= props.max
            }
            onChange={(e) => {
              const key = f.key ?? "";
              props.onChange(
                e.target.checked
                  ? [...chosen, key]
                  : chosen.filter((k) => k !== key),
              );
            }}
          />
          {f.label}
        </label>
      ))}
    </fieldset>
  );
}

const placeholder = "rounded border border-dashed border-border p-2 text-sm";

export function reportConfig(fields: ReportField[]): Config {
  const label = (key: unknown) =>
    fields.find((f) => f.key === key)?.label ??
    (typeof key === "string" ? key : "");
  const options = fields.map((f) => ({
    label: f.label ?? "",
    value: f.key ?? "",
  }));
  const sortable = fields
    .filter((f) => f.sortable)
    .map((f) => ({ label: f.label ?? "", value: f.key ?? "" }));
  return {
    root: {
      fields: { title: { type: "text", label: "Report title" } },
      render: ({ children }: { children?: ReactNode }) => (
        <div className="grid gap-3 p-4">{children}</div>
      ),
    },
    components: {
      Heading: {
        label: "Heading",
        fields: {
          text: { type: "text", label: "Text" },
          level: {
            type: "select",
            label: "Level",
            options: [
              { label: "Main", value: 1 },
              { label: "Section", value: 2 },
              { label: "Subsection", value: 3 },
            ],
          },
        },
        defaultProps: { text: "Heading", level: 2 },
        render: ({ text, level }: Props) => (
          <p
            className={level === 1 ? "text-xl font-semibold" : "font-semibold"}
          >
            {String(text)}
          </p>
        ),
      },
      Paragraph: {
        label: "Paragraph",
        fields: { text: { type: "textarea", label: "Text" } },
        defaultProps: { text: "Write the paragraph here." },
        render: ({ text }: Props) => (
          <p className="whitespace-pre-line">{String(text)}</p>
        ),
      },
      FieldValue: {
        label: "Field value",
        fields: {
          field: { type: "select", label: "Field", options },
          label: { type: "text", label: "Label (optional)" },
        },
        defaultProps: { field: "item.title", label: null },
        render: ({ field }: Props) => (
          <p className={placeholder}>Value of {label(field)} (first item)</p>
        ),
      },
      ItemsTable: {
        label: "Items table",
        fields: {
          columns: {
            type: "custom",
            label: "Columns",
            render: ({ value, onChange }) => (
              <FieldChecks
                fields={fields}
                value={value as unknown}
                onChange={onChange}
                max={12}
              />
            ),
          },
          sort: {
            type: "select",
            label: "Sort by",
            options: [{ label: "None", value: null }, ...sortable],
          },
          direction: {
            type: "radio",
            label: "Order",
            options: [
              { label: "Newest or Z first", value: "desc" },
              { label: "Oldest or A first", value: "asc" },
            ],
          },
          limit: { type: "number", label: "Rows (1 to 500)", min: 1, max: 500 },
          caption: { type: "text", label: "Caption (optional)" },
        },
        defaultProps: {
          columns: ["item.title", "jurisdiction.names", "item.last_changed_at"],
          sort: "item.last_changed_at",
          direction: "desc",
          limit: 50,
          caption: null,
        },
        render: ({ columns, limit }: Props) => (
          <p className={placeholder}>
            Items table:{" "}
            {(Array.isArray(columns) ? columns : []).map(label).join(", ")} (up
            to {String(limit)} rows)
          </p>
        ),
      },
      ChangeList: {
        label: "Latest changes",
        fields: {
          title: { type: "text", label: "Title (optional)" },
          limit: {
            type: "number",
            label: "Changes (1 to 100)",
            min: 1,
            max: 100,
          },
        },
        defaultProps: { title: "Latest changes", limit: 10 },
        render: ({ limit }: Props) => (
          <p className={placeholder}>Latest {String(limit)} changes</p>
        ),
      },
      JurisdictionSummary: {
        label: "Jurisdiction summary",
        fields: { title: { type: "text", label: "Title (optional)" } },
        defaultProps: { title: "By jurisdiction" },
        render: () => (
          <p className={placeholder}>
            Items and highest severity per jurisdiction
          </p>
        ),
      },
      PageBreak: {
        label: "Page break",
        fields: {},
        render: () => <hr aria-label="Page break" className="border-dashed" />,
      },
      HeaderFooter: {
        label: "Header and footer",
        fields: {
          header_text: { type: "text", label: "Header (optional)" },
          footer_text: { type: "text", label: "Footer (optional)" },
          page_numbers: {
            type: "radio",
            label: "Page numbers",
            options: [
              { label: "Yes", value: true },
              { label: "No", value: false },
            ],
          },
          date: {
            type: "radio",
            label: "Date prepared",
            options: [
              { label: "Yes", value: true },
              { label: "No", value: false },
            ],
          },
        },
        defaultProps: {
          header_text: null,
          footer_text: null,
          page_numbers: true,
          date: true,
        },
        render: () => (
          <p className={placeholder}>
            Header and footer settings (printed pages)
          </p>
        ),
      },
      LegalMarkings: {
        label: "Legal markings",
        fields: {},
        render: () => (
          <p className={placeholder}>
            Company name, address and required markings (from Branding)
          </p>
        ),
      },
    },
  };
}
