/**
 * "New output" on the Outputs page (screens.md; M8.6b): a PDF, an email with the PDF, or a CSV,
 * now or on a schedule. Only the kinds and sources the user may use are offered; the API checks
 * every one again, and its answer is shown as it comes.
 */
import { useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { viewsQuery } from "@/features/me/api";
import { layoutsQuery } from "@/features/reports/api";
import { problemText } from "@/lib/auth/session";

import { templatesQuery, useCreateOutput, type OutputRequest } from "./api";

type Kind = "pdf" | "email" | "csv";
const KINDS: { kind: Kind; label: string; permission: string }[] = [
  { kind: "pdf", label: "PDF download", permission: "outputs.pdf" },
  { kind: "email", label: "Email with the PDF", permission: "outputs.email" },
  { kind: "csv", label: "CSV export", permission: "outputs.csv" },
];
const REPEATS = [
  { cron: "0 7 * * 1", label: "Every Monday at 07:00" },
  { cron: "0 7 * * *", label: "Every day at 07:00" },
  { cron: "0 7 1 * *", label: "On the 1st of each month at 07:00" },
];
const field = "rounded border border-border bg-surface px-2 py-1";
const MAX_RECIPIENTS = 20; // as the server (outputs/mail.py)
/** Every item, newest change first, as the search export writes it (the page is not used). */
const ALL_ITEMS = {
  sort: "last_changed_desc",
  page: 1,
  page_size: 50,
  highlight: false,
  facet_counts: false,
} as const;

export function NewOutput(props: { can: (permission: string) => boolean }) {
  const id = useId();
  const kinds = KINDS.filter((k) => props.can(k.permission));
  const [kind, setKind] = useState<Kind>(kinds[0]?.kind ?? "pdf");
  const [source, setSource] = useState("");
  const [emails, setEmails] = useState("");
  const [subject, setSubject] = useState("");
  const [repeat, setRepeat] = useState(false);
  const [cron, setCron] = useState(REPEATS[0]?.cron ?? "");
  const templates = useQuery({
    ...templatesQuery,
    enabled: props.can("reports.print") && kind !== "csv",
  });
  const layouts = useQuery({
    ...layoutsQuery,
    enabled: props.can("reports.build") && kind !== "csv",
  });
  const views = useQuery({
    ...viewsQuery,
    enabled: props.can("items.read") && kind === "csv",
  });
  const create = useCreateOutput();
  if (kinds.length === 0) return null;

  // One address a line; blank lines and repeats dropped. The server checks each again.
  const addresses = [
    ...new Set(
      emails
        .split(/\n/)
        .map((a) => a.trim())
        .filter(Boolean),
    ),
  ];
  const tooMany = kind === "email" && addresses.length > MAX_RECIPIENTS;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (tooMany) return;
    const [type, value = ""] = source.split(":", 2);
    const body: OutputRequest = {
      kind,
      source:
        type === "t"
          ? { report_template_key: value }
          : type === "l"
            ? { report_layout_id: value }
            : type === "v"
              ? { saved_view_id: value }
              : { query: ALL_ITEMS },
    };
    if (kind === "email")
      body.destination = {
        emails: addresses,
        ...(subject.trim() ? { subject: subject.trim() } : {}),
        copies: 1,
      };
    if (repeat) body.schedule = { cron };
    create.mutate(body);
  };

  const pdfSources = (
    <>
      <option value="">Choose a report</option>
      {templates.data && templates.data.length > 0 && (
        <optgroup label="Stock reports">
          {templates.data.map((t) => (
            <option key={t.key} value={`t:${t.key ?? ""}`}>
              {t.label}
            </option>
          ))}
        </optgroup>
      )}
      {layouts.data && layouts.data.length > 0 && (
        <optgroup label="Reports">
          {layouts.data.map((l) => (
            <option key={l.id} value={`l:${l.id}`}>
              {l.name}
            </option>
          ))}
        </optgroup>
      )}
    </>
  );
  const csvSources = (
    <>
      <option value="all">All items</option>
      {views.data?.map((v) => (
        <option key={v.id} value={`v:${v.id}`}>
          Saved view: {v.name}
        </option>
      ))}
    </>
  );

  return (
    <form
      aria-labelledby={`${id}-title`}
      className="flex max-w-xl flex-col gap-3 rounded border border-border p-3"
      onSubmit={submit}
    >
      <h2 id={`${id}-title`} className="text-lg font-semibold">
        New output
      </h2>
      <label className="flex flex-col gap-1">
        What
        <select
          className={field}
          value={kind}
          onChange={(e) => {
            const next = e.target.value as Kind;
            setKind(next);
            setSource(next === "csv" ? "all" : "");
          }}
        >
          {kinds.map((k) => (
            <option key={k.kind} value={k.kind}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        {kind === "csv" ? "Items" : "Report"}
        <select
          className={field}
          required
          value={kind === "csv" && source === "" ? "all" : source}
          onChange={(e) => {
            setSource(e.target.value);
          }}
        >
          {kind === "csv" ? csvSources : pdfSources}
        </select>
      </label>
      {kind === "email" && (
        <>
          <label className="flex flex-col gap-1">
            Recipients, one address a line
            <textarea
              className={field}
              required
              rows={3}
              aria-invalid={tooMany}
              aria-describedby={`${id}-recipients`}
              value={emails}
              onChange={(e) => {
                setEmails(e.target.value);
              }}
            />
          </label>
          <p
            id={`${id}-recipients`}
            className={
              tooMany ? "text-sm text-critical" : "text-sm text-text-muted"
            }
          >
            {tooMany
              ? `At most ${String(MAX_RECIPIENTS)} recipients; this has ${String(addresses.length)}.`
              : `Up to ${String(MAX_RECIPIENTS)} addresses in the allowed domains, one per line.`}
          </p>
          <label className="flex flex-col gap-1">
            Subject (optional)
            <input
              className={field}
              maxLength={200}
              value={subject}
              onChange={(e) => {
                setSubject(e.target.value);
              }}
            />
          </label>
        </>
      )}
      {props.can("outputs.schedule") && (
        <fieldset className="flex flex-col gap-2">
          <legend className="sr-only">Schedule</legend>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={repeat}
              onChange={(e) => {
                setRepeat(e.target.checked);
              }}
            />
            Repeat on a schedule, in your time zone
          </label>
          {repeat && (
            <label className="flex flex-col gap-1">
              When
              <select
                className={field}
                value={cron}
                onChange={(e) => {
                  setCron(e.target.value);
                }}
              >
                {REPEATS.map((r) => (
                  <option key={r.cron} value={r.cron}>
                    {r.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </fieldset>
      )}
      <div>
        <button
          type="submit"
          className="rounded border border-border px-3 py-1 disabled:opacity-50"
          disabled={create.isPending || tooMany}
        >
          {repeat ? "Schedule" : "Request"}
        </button>
      </div>
      {create.isError && (
        <p role="alert" className="text-critical">
          {problemText(create.error, "The output could not be requested.")}
        </p>
      )}
      <p role="status" className="text-sm">
        {create.isSuccess &&
          (create.data.scheduled_cron
            ? "Scheduled. It is listed under Schedules."
            : "Requested. It appears in the history below when it is ready.")}
      </p>
    </form>
  );
}
