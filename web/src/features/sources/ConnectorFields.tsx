/**
 * A connector kind's settings form, rendered from its JSON Schema in connectors.yaml
 * (screens.md: "connector form generated from connectors.yaml").
 *
 * Handles the shapes the contract uses: strings (URLs among them), enums, booleans, bounded
 * integers and numbers, and lists of strings, entered one per line. The API validates on save
 * and names the field that failed, so this form only helps; it is not the check.
 */
import { CONNECTORS } from "./connectors.generated";

export interface FieldSchema {
  type?: string;
  format?: string;
  enum?: readonly string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  minItems?: number;
  maxItems?: number;
  description?: string;
  items?: FieldSchema;
}

export interface ObjectSchema {
  properties: Readonly<Record<string, FieldSchema>>;
  required?: readonly string[];
}

export type Values = Record<string, unknown>;

export const KINDS = Object.keys(
  CONNECTORS.kinds,
) as (keyof typeof CONNECTORS.kinds)[];

export function kindSchema(kind: string): ObjectSchema | null {
  const kinds = CONNECTORS.kinds as unknown as Record<string, ObjectSchema>;
  return kinds[kind] ?? null;
}

export const RULES_SCHEMA =
  CONNECTORS.extraction_rules as unknown as ObjectSchema;

const field = "rounded border border-border bg-bg px-2 py-1";

/** Form state for a stored config: lists shown one entry per line. */
export function toForm(schema: ObjectSchema, stored: Values): Values {
  const out: Values = {};
  for (const [name, prop] of Object.entries(schema.properties)) {
    const value = stored[name] ?? prop.default;
    if (prop.type === "array")
      out[name] = Array.isArray(value)
        ? value.filter((v): v is string => typeof v === "string").join("\n")
        : "";
    else if (prop.type === "boolean") out[name] = Boolean(value);
    else
      out[name] =
        typeof value === "string" || typeof value === "number"
          ? String(value)
          : "";
  }
  return out;
}

/** What to send: empty fields left out, so the API applies the contract's defaults. */
export function fromForm(schema: ObjectSchema, form: Values): Values {
  const out: Values = {};
  for (const [name, prop] of Object.entries(schema.properties)) {
    const raw = form[name];
    if (prop.type === "boolean") {
      out[name] = Boolean(raw);
      continue;
    }
    const text = typeof raw === "string" ? raw.trim() : "";
    if (!text) continue;
    if (prop.type === "array") {
      out[name] = text
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
    } else if (prop.type === "integer" || prop.type === "number") {
      const n = Number(text);
      out[name] = Number.isFinite(n) ? n : text; // a non-number is the API's to refuse
    } else {
      out[name] = text;
    }
  }
  return out;
}

function label(name: string): string {
  const words = name.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function ConnectorFields({
  schema,
  values,
  onChange,
  idPrefix,
  disabled = false,
}: {
  schema: ObjectSchema;
  values: Values;
  onChange: (next: Values) => void;
  idPrefix: string;
  disabled?: boolean;
}) {
  const required = new Set(schema.required ?? []);
  return (
    <>
      {Object.entries(schema.properties).map(([name, prop]) => {
        const id = `${idPrefix}-${name}`;
        const hint = prop.description ? `${id}-hint` : undefined;
        const set = (value: unknown) => {
          onChange({ ...values, [name]: value });
        };
        const text = typeof values[name] === "string" ? values[name] : "";
        const caption = (
          <span>
            {label(name)}
            {required.has(name) && <span aria-hidden="true"> *</span>}
          </span>
        );
        const description = hint && (
          <span id={hint} className="text-sm text-text-muted">
            {prop.description}
          </span>
        );
        if (prop.type === "boolean") {
          return (
            <label key={name} className="flex items-start gap-2">
              <input
                id={id}
                type="checkbox"
                checked={Boolean(values[name])}
                disabled={disabled}
                aria-describedby={hint}
                onChange={(e) => {
                  set(e.target.checked);
                }}
              />
              <span className="flex flex-col">
                {caption}
                {description}
              </span>
            </label>
          );
        }
        let control;
        if (prop.enum) {
          control = (
            <select
              id={id}
              value={text}
              disabled={disabled}
              aria-describedby={hint}
              className={field}
              onChange={(e) => {
                set(e.target.value);
              }}
            >
              <option value="">(default)</option>
              {prop.enum.map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          );
        } else if (prop.type === "array") {
          control = (
            <textarea
              id={id}
              value={text}
              rows={3}
              disabled={disabled}
              required={required.has(name)}
              aria-describedby={hint}
              className={field}
              onChange={(e) => {
                set(e.target.value);
              }}
            />
          );
        } else {
          const numeric = prop.type === "integer" || prop.type === "number";
          control = (
            <input
              id={id}
              type={numeric ? "number" : prop.format === "uri" ? "url" : "text"}
              value={text}
              min={prop.minimum}
              max={prop.maximum}
              step={prop.type === "number" ? "any" : undefined}
              disabled={disabled}
              required={required.has(name)}
              aria-describedby={hint}
              className={field}
              onChange={(e) => {
                set(e.target.value);
              }}
            />
          );
        }
        return (
          <div key={name} className="flex flex-col gap-1">
            <label htmlFor={id}>
              {caption}
              {prop.type === "array" && (
                <span className="text-text-muted"> (one per line)</span>
              )}
            </label>
            {control}
            {description}
          </div>
        );
      })}
    </>
  );
}
