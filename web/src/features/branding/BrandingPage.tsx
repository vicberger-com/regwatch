import { useQuery } from "@tanstack/react-query";
import { useState, type ChangeEvent, type FormEvent } from "react";

import { problemText } from "@/lib/auth/session";
import { settingsQuery } from "@/features/settings/api";

import {
  brandingQuery,
  COLOR,
  legalQuery,
  MAX_LOGO_BYTES,
  useSaveBranding,
  useSaveLegal,
  useUploadLogo,
  type Branding,
} from "./api";

const field = "rounded border border-border bg-bg px-2 py-1";
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";
const panel = "flex flex-col gap-3 rounded border border-border bg-surface p-3";

/** `/admin/branding` (screens.md): logo, title, company fields, colour, legal page. */
export function BrandingPage() {
  const branding = useQuery(brandingQuery);
  if (branding.isPending) return <p>Loading branding…</p>;
  if (branding.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(branding.error, "The branding could not be loaded.")}
      </p>
    );
  }
  return (
    <section aria-labelledby="branding-heading" className="flex flex-col gap-4">
      <h1 id="branding-heading" className="text-2xl font-semibold">
        Branding and legal
      </h1>
      <LogoForm branding={branding.data} />
      <BrandingForm
        key={JSON.stringify(branding.data)}
        branding={branding.data}
      />
      <LegalForm />
    </section>
  );
}

function LogoForm({ branding }: { branding: Branding }) {
  const upload = useUploadLogo();
  const [refused, setRefused] = useState<string | null>(null);

  function choose(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    upload.reset();
    if (file.size > MAX_LOGO_BYTES) {
      setRefused("The logo is larger than 1 MB.");
      return;
    }
    setRefused(null);
    upload.mutate(file);
  }

  const message =
    refused ??
    (upload.isError
      ? problemText(upload.error, "The logo could not be saved.")
      : null);
  return (
    <div role="group" aria-labelledby="logo-heading" className={panel}>
      <h2 id="logo-heading" className="font-semibold">
        Logo
      </h2>
      {branding.logo_url ? (
        <img
          src={branding.logo_url}
          alt="Current logo"
          className="h-14 w-auto self-start"
        />
      ) : (
        <p className="text-text-muted">No logo yet.</p>
      )}
      <label
        className={`${button} cursor-pointer focus-within:[outline:var(--focus-width)_solid_var(--focus)] self-start`}
      >
        Upload a PNG or SVG (at most 1 MB)
        <input
          type="file"
          accept="image/png,image/svg+xml,.png,.svg"
          className="sr-only"
          disabled={upload.isPending}
          onChange={choose}
        />
      </label>
      <p role="status">{upload.isSuccess ? "Logo saved." : ""}</p>
      {message && (
        <p role="alert" className="text-critical">
          {message}
        </p>
      )}
    </div>
  );
}

const TEXT_FIELDS = [
  ["site_title", "Site title", 80],
  ["company_name", "Company name", 200],
  ["company_short_name", "Short company name", 40],
] as const;

function BrandingForm({ branding }: { branding: Branding }) {
  const save = useSaveBranding();
  const [values, setValues] = useState({
    site_title: branding.site_title ?? "",
    company_name: branding.company_name ?? "",
    company_short_name: branding.company_short_name ?? "",
    company_address: branding.company_address ?? "",
    primary_color: branding.primary_color ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof values, value: string) => {
    setValues({ ...values, [key]: value });
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    const color = values.primary_color.trim();
    if (color && !COLOR.test(color)) {
      setError(
        "The primary colour is a hex value such as #1F5AA6, or empty for the default.",
      );
      return;
    }
    setError(null);
    save.mutate({ ...values, primary_color: color || null });
  }

  const message =
    error ??
    (save.isError
      ? problemText(save.error, "The branding could not be saved.")
      : null);
  return (
    <form onSubmit={submit} noValidate aria-label="Branding" className={panel}>
      <h2 className="font-semibold">Title and company</h2>
      {TEXT_FIELDS.map(([key, label, max]) => (
        <label key={key} className="flex flex-col gap-1">
          <span>{label}</span>
          <input
            value={values[key]}
            maxLength={max}
            onChange={(e) => {
              set(key, e.target.value);
            }}
            className={field}
          />
        </label>
      ))}
      <label className="flex flex-col gap-1">
        <span>Company address</span>
        <textarea
          rows={3}
          maxLength={500}
          value={values.company_address}
          onChange={(e) => {
            set("company_address", e.target.value);
          }}
          className={field}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span>Primary colour (hex, empty for the default)</span>
        <input
          value={values.primary_color}
          placeholder="#1F5AA6"
          onChange={(e) => {
            set("primary_color", e.target.value);
          }}
          className={`${field} w-32 font-mono`}
        />
      </label>
      <p role="status">{save.isSuccess ? "Branding saved." : ""}</p>
      {message && (
        <p role="alert" className="text-critical">
          {message}
        </p>
      )}
      <button
        type="submit"
        className={`${button} self-start`}
        disabled={save.isPending}
      >
        Save branding
      </button>
    </form>
  );
}

function LegalForm() {
  // The stored Markdown comes from the settings list (same permission), so the editor starts
  // from the current page instead of empty, and saving never wipes text by accident.
  const legal = useQuery(legalQuery);
  const settings = useQuery(settingsQuery);
  if (legal.isPending || settings.isPending)
    return <p>Loading the legal page…</p>;
  if (legal.isError || settings.isError) {
    return (
      <p role="alert" className="text-critical">
        {problemText(
          legal.error ?? settings.error,
          "The legal page could not be loaded.",
        )}
      </p>
    );
  }
  const stored = (key: string) => {
    const value = settings.data.find((s) => s.key === key)?.value;
    return typeof value === "string" ? value : "";
  };
  return (
    <LegalEditor
      html={legal.data.html ?? ""}
      source={stored("legal.page_markdown")}
      markings={stored("legal.required_markings")}
    />
  );
}

function LegalEditor({
  html,
  source,
  markings,
}: {
  html: string;
  source: string;
  markings: string;
}) {
  const save = useSaveLegal();
  const [markdown, setMarkdown] = useState(source);
  const [required, setRequired] = useState(markings);
  const [touched, setTouched] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({ page_markdown: markdown, required_markings: required });
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label="Legal page"
      className={panel}
    >
      <h2 className="font-semibold">Legal page</h2>
      <label className="flex flex-col gap-1">
        <span>
          Page text in Markdown{" "}
          <span className="text-sm text-text-muted">
            replaces the whole page when saved; HTML and images are not shown
          </span>
        </span>
        <textarea
          rows={10}
          maxLength={200_000}
          value={markdown}
          onChange={(e) => {
            setMarkdown(e.target.value);
            setTouched(true);
          }}
          className={`${field} font-mono`}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span>Required markings (report and email footers)</span>
        <input
          value={required}
          maxLength={2000}
          onChange={(e) => {
            setRequired(e.target.value);
            setTouched(true);
          }}
          className={field}
        />
      </label>
      <p role="status">{save.isSuccess ? "Legal page saved." : ""}</p>
      {save.isError && (
        <p role="alert" className="text-critical">
          {problemText(save.error, "The legal page could not be saved.")}
        </p>
      )}
      <button
        type="submit"
        className={`${button} self-start`}
        disabled={save.isPending || !touched}
      >
        Save legal page
      </button>
      <h3 className="font-semibold">Preview of the saved page</h3>
      <LegalHtml html={html} />
    </form>
  );
}

/**
 * The API's legal page HTML. It is rendered from Markdown with raw HTML off and then sanitized
 * with nh3 on the server (regwatch.admin.legal), so it holds only headings, paragraphs, lists,
 * emphasis, code, quotes, tables and http, https or mailto links; the page CSP blocks scripts too.
 */
export function LegalHtml({ html }: { html: string }) {
  if (!html) return <p className="text-text-muted">The legal page is empty.</p>;
  return (
    <div
      className="prose max-w-none"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
