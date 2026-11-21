/**
 * `/admin/printers` (screens.md; M8.5b, CP-33): an administrator's network printers. The
 * server checks each address against the allowed printer networks when it is saved and again
 * before each job; this page shows its answer as it comes.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { failure, problemText } from "@/lib/auth/session";

type Printer = Schemas["Printer"];
type PrinterWrite = Schemas["PrinterWrite"];
const button = "rounded border border-border px-2 py-1 disabled:opacity-50";
const field = "rounded border border-border bg-surface px-2 py-1";
const KEY = ["admin", "printers"];

const printersQuery = {
  queryKey: KEY,
  queryFn: async (): Promise<Printer[]> => {
    const result = await api.GET("/admin/printers");
    if (!result.response.ok || result.data === undefined) throw failure(result);
    return result.data;
  },
};

function useChange() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (
      change:
        | { op: "create"; body: PrinterWrite }
        | { op: "update"; id: string; body: PrinterWrite }
        | { op: "delete"; id: string }
        | { op: "test"; id: string },
    ) => {
      const result =
        change.op === "create"
          ? await api.POST("/admin/printers", { body: change.body })
          : change.op === "update"
            ? await api.PATCH("/admin/printers/{id}", {
                params: { path: { id: change.id } },
                body: change.body,
              })
            : change.op === "delete"
              ? await api.DELETE("/admin/printers/{id}", {
                  params: { path: { id: change.id } },
                })
              : await api.POST("/admin/printers/{id}/test-page", {
                  params: { path: { id: change.id } },
                });
      if (!result.response.ok) throw failure(result);
      return change.op;
    },
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
}

export function PrintersPage() {
  const id = useId();
  const printers = useQuery(printersQuery);
  const change = useChange();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [pin, setPin] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    change.mutate(
      {
        op: "create",
        body: {
          name: name.trim(),
          ipp_url: url.trim(),
          ...(pin.trim() ? { tls_sha256: pin.trim() } : {}),
        },
      },
      {
        onSuccess: () => {
          setName("");
          setUrl("");
          setPin("");
        },
      },
    );
  };

  return (
    <section aria-labelledby={`${id}-h`} className="flex flex-col gap-4">
      <h1 id={`${id}-h`} className="text-2xl font-semibold">
        Printers
      </h1>
      <p className="max-w-3xl text-sm text-text-muted">
        Network printers that users with the print permission can choose in New
        output, while the Server printing flag is on. An address must be inside
        the allowed printer networks (Settings).
      </p>
      {change.isError && (
        <p role="alert" className="text-critical">
          {problemText(change.error, "The change could not be made.")}
        </p>
      )}
      <p role="status" className="text-sm">
        {change.isSuccess &&
          (change.data === "test"
            ? "Test page queued. It appears in the Outputs history."
            : "Saved.")}
      </p>
      {printers.isPending ? (
        <p>Loading printers…</p>
      ) : printers.isError ? (
        <p role="alert" className="text-critical">
          {problemText(printers.error, "The printers could not be loaded.")}
        </p>
      ) : printers.data.length === 0 ? (
        <p className="text-sm text-text-muted">No printers yet.</p>
      ) : (
        <table className="w-full max-w-4xl text-sm">
          <thead>
            <tr>
              <th scope="col" className="text-left">
                Name
              </th>
              <th scope="col" className="text-left">
                Address
              </th>
              <th scope="col" className="text-left">
                Certificate
              </th>
              <th scope="col" className="text-left">
                State
              </th>
              <th scope="col" className="text-left">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {printers.data.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>
                  <code>{p.ipp_url}</code>
                </td>
                <td>{p.tls_sha256 ? "Pinned" : "Verified"}</td>
                <td>{p.enabled ? "Enabled" : "Disabled"}</td>
                <td className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={button}
                    aria-label={`${p.enabled ? "Disable" : "Enable"} ${p.name ?? ""}`}
                    disabled={change.isPending}
                    onClick={() => {
                      if (p.id)
                        change.mutate({
                          op: "update",
                          id: p.id,
                          body: { enabled: !p.enabled },
                        });
                    }}
                  >
                    {p.enabled ? "Disable" : "Enable"}
                  </button>
                  <button
                    type="button"
                    className={button}
                    aria-label={`Print a test page on ${p.name ?? ""}`}
                    disabled={change.isPending || !p.enabled}
                    onClick={() => {
                      if (p.id) change.mutate({ op: "test", id: p.id });
                    }}
                  >
                    Test page
                  </button>
                  <button
                    type="button"
                    className={button}
                    aria-label={`Delete ${p.name ?? ""}`}
                    disabled={change.isPending}
                    onClick={() => {
                      if (
                        p.id &&
                        window.confirm(`Delete the printer ${p.name ?? ""}?`)
                      )
                        change.mutate({ op: "delete", id: p.id });
                    }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form
        aria-labelledby={`${id}-add`}
        className="flex max-w-xl flex-col gap-2 rounded border border-border p-3"
        onSubmit={submit}
      >
        <h2 id={`${id}-add`} className="text-lg font-semibold">
          Add a printer
        </h2>
        <label className="flex flex-col gap-1">
          Name
          <input
            className={field}
            required
            maxLength={100}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        </label>
        <label className="flex flex-col gap-1">
          Address
          <input
            className={field}
            required
            maxLength={500}
            placeholder="ipps://printer.example.internal/ipp/print"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
            }}
          />
        </label>
        <label className="flex flex-col gap-1">
          Certificate fingerprint, SHA-256 (optional, for a self-signed
          certificate)
          <input
            className={field}
            maxLength={95}
            value={pin}
            onChange={(e) => {
              setPin(e.target.value);
            }}
          />
        </label>
        <div>
          <button type="submit" className={button} disabled={change.isPending}>
            Add
          </button>
        </div>
      </form>
    </section>
  );
}
