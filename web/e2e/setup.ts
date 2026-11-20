/**
 * Data for the end-to-end tests: one manual source "E2E uploads" with two plain-text documents
 * (a German one naming the BSI, an EU one), uploaded through the API and processed by the
 * stack's own worker. Idempotent: an existing source is reused.
 */
import { apiSession, MARK } from "./session";

const DOCUMENTS = [
  {
    title: `E2E: NIS2 incident reporting guidance (${MARK})`,
    text: "Das Bundesamt für Sicherheit in der Informationstechnik (BSI) veröffentlicht Hinweise zur Meldung von Sicherheitsvorfällen nach NIS2 für Betreiber in Deutschland. regwatch-e2e-fixture",
  },
  {
    title: `E2E: European Commission data protection notice (${MARK})`,
    text: "The European Commission published a notice on data protection obligations for providers in the European Union under the GDPR. regwatch-e2e-fixture",
  },
];

async function sleep(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export default async function setup(): Promise<void> {
  const api = await apiSession();
  const sources = (await (await api.get("/api/v1/sources")).json()) as
    { items?: { id: string; name: string }[] } | { id: string; name: string }[];
  const list = Array.isArray(sources) ? sources : (sources.items ?? []);
  let source = list.find(
    (s) =>
      s.name === "E2E uploads" && (s as { kind?: string }).kind === "manual",
  );
  if (!source) {
    const made = await api.post("/api/v1/sources", {
      data: { name: "E2E uploads", kind: "manual", config: {} },
    });
    if (made.status() !== 201)
      throw new Error(`creating the source: HTTP ${String(made.status())}`);
    source = (await made.json()) as { id: string; name: string };
  }
  for (const doc of DOCUMENTS) {
    const found = await api.post("/api/v1/search", {
      data: { q: `"${doc.title}"`, facet_counts: false },
    });
    if (found.ok() && ((await found.json()) as { total: number }).total > 0)
      continue;
    for (let attempt = 0; attempt < 30; attempt++) {
      const sent = await api.post(`/api/v1/sources/${source.id}/documents`, {
        multipart: {
          file: {
            name: "doc.txt",
            mimeType: "text/plain",
            buffer: Buffer.from(doc.text),
          },
          title: doc.title,
        },
      });
      if (sent.status() === 202) break;
      if (sent.status() !== 409)
        throw new Error(`uploading: HTTP ${String(sent.status())}`);
      await sleep(2000); // one run at a time per source
    }
  }
  for (let attempt = 0; attempt < 60; attempt++) {
    const got = await api.post("/api/v1/search", {
      data: { q: MARK, facet_counts: false },
    });
    if (
      got.ok() &&
      ((await got.json()) as { total: number }).total >= DOCUMENTS.length
    )
      return;
    await sleep(2000);
  }
  throw new Error(
    "the uploaded documents did not become items within two minutes",
  );
}
