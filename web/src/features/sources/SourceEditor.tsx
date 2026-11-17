import { useState, type FormEvent } from "react";

import { problemText } from "@/lib/auth/session";

import {
  useSaveSource,
  type CaptureJobWrite,
  type Source,
  type SourceWrite,
} from "./api";
import {
  ConnectorFields,
  fromForm,
  KINDS,
  kindSchema,
  toForm,
  type Values,
} from "./ConnectorFields";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";
const CREDIBILITY = ["official", "secondary", "news"] as const;
type Credibility = (typeof CREDIBILITY)[number];

/** Create or edit a source with its capture job (screens.md `/admin/sources`). */
export function SourceEditor({
  current,
  canOverride,
  onDone,
}: {
  current: Source | null;
  canOverride: boolean;
  onDone: () => void;
}) {
  const save = useSaveSource();
  const job = current?.job;
  const [name, setName] = useState(current?.name ?? "");
  const [kind, setKind] = useState<string>(current?.kind ?? "rss");
  const [credibility, setCredibility] = useState<Credibility>(
    current?.credibility ?? "official",
  );
  const [override, setOverride] = useState(
    current?.robots_policy === "override",
  );
  const [reason, setReason] = useState(current?.override_reason ?? "");
  const schema = kindSchema(kind);
  const [config, setConfig] = useState<Values>(() =>
    schema ? toForm(schema, current?.config ?? {}) : {},
  );
  const [schedule, setSchedule] = useState<"interval" | "cron">(
    job?.cron ? "cron" : "interval",
  );
  const [minutes, setMinutes] = useState(
    String((job?.interval_seconds ?? 3600) / 60),
  );
  const [cron, setCron] = useState(job?.cron ?? "");
  const [timezone, setTimezone] = useState(job?.timezone ?? "UTC");
  const [maxItems, setMaxItems] = useState(
    String(job?.max_items_per_run ?? 200),
  );
  const [rate, setRate] = useState(String(job?.rate_limit_per_minute ?? 30));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!schema) return;
    const jobBody: CaptureJobWrite = {
      timezone,
      max_items_per_run: Number(maxItems),
      rate_limit_per_minute: Number(rate),
      ...(schedule === "cron"
        ? { cron, interval_seconds: null }
        : { interval_seconds: Math.round(Number(minutes) * 60), cron: null }),
    };
    const body: SourceWrite = {
      name,
      credibility,
      // The contract types config as an object of any shape; the API checks it per kind.
      config: fromForm(schema, config) as NonNullable<SourceWrite["config"]>,
      job: jobBody,
      ...(current ? {} : { kind: kind as SourceWrite["kind"] & string }),
    };
    // Only holders of sources.override_robots see or change the override (M3 acceptance 4);
    // the API checks the permission again.
    if (canOverride) {
      body.robots_policy = override ? "override" : "respect";
      if (override) body.override_reason = reason;
    }
    save.mutate(
      { ...(current ? { id: current.id } : {}), body },
      { onSuccess: onDone },
    );
  }

  return (
    <form
      onSubmit={submit}
      aria-label={current ? `Edit source ${current.name}` : "Create source"}
      className="flex max-w-xl flex-col gap-3 rounded border border-border p-3"
    >
      <h2 className="text-xl font-semibold">
        {current ? `Edit ${current.name}` : "Create source"}
      </h2>
      <label className="flex flex-col gap-1">
        <span>Name</span>
        <input
          value={name}
          required
          maxLength={200}
          className={field}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span>Kind</span>
        <select
          value={kind}
          disabled={current !== null}
          className={field}
          onChange={(e) => {
            const next = e.target.value;
            setKind(next);
            const nextSchema = kindSchema(next);
            setConfig(nextSchema ? toForm(nextSchema, {}) : {});
          }}
        >
          {KINDS.map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span>Credibility</span>
        <select
          value={credibility}
          className={field}
          onChange={(e) => {
            setCredibility(e.target.value as Credibility);
          }}
        >
          {CREDIBILITY.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </label>
      <fieldset className="flex flex-col gap-2 rounded border border-border p-2">
        <legend>Connector settings</legend>
        {schema && (
          <ConnectorFields
            schema={schema}
            values={config}
            onChange={setConfig}
            idPrefix="cfg"
          />
        )}
      </fieldset>
      <fieldset className="flex flex-col gap-2 rounded border border-border p-2">
        <legend>Capture job</legend>
        <div className="flex gap-4">
          {(["interval", "cron"] as const).map((mode) => (
            <label key={mode} className="flex items-center gap-1">
              <input
                type="radio"
                name="schedule"
                checked={schedule === mode}
                onChange={() => {
                  setSchedule(mode);
                }}
              />
              {mode === "interval" ? "Every N minutes" : "Cron expression"}
            </label>
          ))}
        </div>
        {schedule === "interval" ? (
          <label className="flex flex-col gap-1">
            <span>Minutes between runs (at least 15)</span>
            <input
              type="number"
              min={15}
              value={minutes}
              className={field}
              onChange={(e) => {
                setMinutes(e.target.value);
              }}
            />
          </label>
        ) : (
          <label className="flex flex-col gap-1">
            <span>Cron (minute hour day month weekday)</span>
            <input
              value={cron}
              className={field}
              onChange={(e) => {
                setCron(e.target.value);
              }}
            />
          </label>
        )}
        <label className="flex flex-col gap-1">
          <span>Time zone</span>
          <input
            value={timezone}
            className={field}
            onChange={(e) => {
              setTimezone(e.target.value);
            }}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Most items per run</span>
          <input
            type="number"
            min={1}
            max={2000}
            value={maxItems}
            className={field}
            onChange={(e) => {
              setMaxItems(e.target.value);
            }}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Requests per minute to the site</span>
          <input
            type="number"
            min={1}
            max={120}
            value={rate}
            className={field}
            onChange={(e) => {
              setRate(e.target.value);
            }}
          />
        </label>
      </fieldset>
      {canOverride ? (
        <fieldset className="flex flex-col gap-2 rounded border border-border p-2">
          <legend>robots.txt</legend>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={override}
              onChange={(e) => {
                setOverride(e.target.checked);
              }}
            />
            Override robots.txt for this source (audited)
          </label>
          {override && (
            <label className="flex flex-col gap-1">
              <span>Reason (required)</span>
              <textarea
                value={reason}
                required
                maxLength={1000}
                rows={2}
                className={field}
                onChange={(e) => {
                  setReason(e.target.value);
                }}
              />
            </label>
          )}
        </fieldset>
      ) : (
        current?.robots_policy === "override" && (
          <p className="text-sm text-text-muted">
            robots.txt is overridden for this source ({current.override_reason}
            ). Changing where it points needs the override permission.
          </p>
        )
      )}
      {save.isError && (
        <p role="alert" className="text-critical">
          {problemText(save.error, "The source could not be saved.")}
        </p>
      )}
      <div className="flex gap-2">
        <button type="submit" className={button} disabled={save.isPending}>
          Save
        </button>
        <button type="button" className={button} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
