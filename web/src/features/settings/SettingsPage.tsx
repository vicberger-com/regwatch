import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { problemText } from "@/lib/auth/session";

import {
  groupByPrefix,
  parseValue,
  settingsQuery,
  toText,
  useSaveSetting,
  type Setting,
} from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

/** `/admin/settings` (screens.md): settings grouped by prefix, each checked by its type. */
export function SettingsPage() {
  const settings = useQuery(settingsQuery);
  if (settings.isPending) return <p>Loading settings…</p>;
  if (settings.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(settings.error, "The settings could not be loaded.")}
      </p>
    );
  }
  return (
    <section aria-labelledby="settings-heading" className="flex flex-col gap-4">
      <h1 id="settings-heading" className="text-2xl font-semibold">
        Settings
      </h1>
      {groupByPrefix(settings.data).map(([prefix, items]) => (
        <fieldset
          key={prefix}
          className="flex flex-col gap-3 rounded border border-border p-3"
        >
          <legend className="px-1 font-semibold">{prefix}</legend>
          {items.map((s) => (
            <SettingRow key={s.key} setting={s} />
          ))}
        </fieldset>
      ))}
    </section>
  );
}

function SettingRow({ setting }: { setting: Setting }) {
  const save = useSaveSetting();
  const [text, setText] = useState(() => toText(setting));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const id = `setting-${setting.key}`;
  const dirty = text !== toText(setting);

  function submit(event: FormEvent) {
    event.preventDefault();
    setSaved(false);
    const parsed = parseValue(setting, text);
    if ("error" in parsed) {
      setError(parsed.error);
      return;
    }
    setError(null);
    save.mutate(
      { key: setting.key, value: parsed.value },
      {
        onSuccess: (updated) => {
          setText(toText(updated));
          setSaved(true);
        },
      },
    );
  }

  const edit = (value: string) => {
    setText(value);
    setSaved(false);
  };
  let input;
  if (setting.type === "boolean") {
    input = (
      <input
        id={id}
        type="checkbox"
        checked={text === "true"}
        onChange={(e) => {
          edit(String(e.target.checked));
        }}
      />
    );
  } else if (setting.type === "enum") {
    input = (
      <select
        id={id}
        value={text}
        onChange={(e) => {
          edit(e.target.value);
        }}
        className={field}
      >
        {(setting.values ?? []).map((v) => (
          <option key={v}>{v}</option>
        ))}
      </select>
    );
  } else if (setting.type === "list") {
    input = (
      <textarea
        id={id}
        value={text}
        rows={3}
        onChange={(e) => {
          edit(e.target.value);
        }}
        className={field}
      />
    );
  } else {
    input = (
      <input
        id={id}
        value={text}
        inputMode={
          setting.type === "integer"
            ? "numeric"
            : setting.type === "number"
              ? "decimal"
              : undefined
        }
        onChange={(e) => {
          edit(e.target.value);
        }}
        className={field}
      />
    );
  }
  const message =
    error ??
    (save.isError
      ? problemText(save.error, "The setting could not be saved.")
      : null);

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label={setting.key}
      className="flex flex-wrap items-start gap-3"
    >
      <label htmlFor={id} className="flex w-72 flex-col">
        <code>{setting.key}</code>
        <span className="text-sm text-text-muted">
          {setting.type}
          {setting.type === "list" ? ", one per line" : ""}
          {setting.note ? ` · ${setting.note}` : ""}
        </span>
      </label>
      {input}
      <button
        type="submit"
        className={button}
        disabled={!dirty || save.isPending}
      >
        Save
      </button>
      <p role="status" className="text-sm">
        {saved ? "Saved." : ""}
      </p>
      {message && (
        <p role="alert" className="w-full text-critical">
          {message}
        </p>
      )}
    </form>
  );
}
