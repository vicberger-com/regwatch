import { useMutation } from "@tanstack/react-query";
import { useState, type ChangeEvent } from "react";

import { problemText } from "@/lib/auth/session";

import { exportTaxonomy, MAX_IMPORT_BYTES, useImportTaxonomy } from "./api";

const button = "rounded border border-border px-2 py-1 disabled:opacity-50";

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  // Revoked a little later: some browsers cancel a download whose URL goes at once.
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 10_000);
}

/** Export for every reader; import (a YAML file, merged by key) for managers. */
export function TaxonomyTransfer({ canManage }: { canManage: boolean }) {
  const download = useMutation({
    mutationFn: exportTaxonomy,
    onSuccess: (blob) => {
      save(blob, "regwatch-taxonomy.yaml");
    },
  });
  const upload = useImportTaxonomy();
  const [refused, setRefused] = useState<string | null>(null);

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    upload.reset();
    setRefused(null);
    if (file.size > MAX_IMPORT_BYTES) {
      setRefused("The file is larger than 2 MB, the most one import accepts.");
      return;
    }
    if (
      !window.confirm(
        `Import ${file.name}? Facets and terms with matching keys are updated; others are added.`,
      )
    )
      return;
    let text: string;
    try {
      // Strict decoding: a file in another encoding is refused, not silently altered.
      text = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
    } catch {
      setRefused(
        "The file is not UTF-8 text. Save it as UTF-8 and import it again.",
      );
      return;
    }
    upload.mutate(text);
  }

  const summary = upload.data;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        className={button}
        disabled={download.isPending}
        onClick={() => {
          download.mutate();
        }}
      >
        Export YAML
      </button>
      {canManage && (
        <label
          className={`${button} cursor-pointer focus-within:[outline:var(--focus-width)_solid_var(--focus)]`}
        >
          Import YAML
          <input
            type="file"
            accept=".yaml,.yml,application/yaml"
            className="sr-only"
            disabled={upload.isPending}
            onChange={(e) => {
              void choose(e);
            }}
          />
        </label>
      )}
      <p role="status">
        {summary &&
          `Imported: ${String(summary.facets_created ?? 0)} facets added, ${String(summary.facets_updated ?? 0)} updated; ${String(summary.terms_created ?? 0)} terms added, ${String(summary.terms_updated ?? 0)} updated.`}
      </p>
      {(refused !== null || upload.isError || download.isError) && (
        <p role="alert" className="w-full text-critical">
          {refused ??
            (upload.isError
              ? problemText(upload.error, "The import failed.")
              : problemText(download.error, "The export failed."))}
        </p>
      )}
    </div>
  );
}
