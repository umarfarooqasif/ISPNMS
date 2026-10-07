"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice, PageHeader, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import { SESSION_LABEL, summaryView } from "@/lib/importview";
import type { ImportSession } from "@/lib/types";

const MAX_MB = 50;

export default function ImportPage() {
  const router = useRouter();
  const can = useCan();
  const sessions = useFetch<ImportSession[]>("/imports");
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState(false);

  async function upload(force: boolean) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const created = await api<ImportSession>(`/imports/wasooli${force ? "?force=true" : ""}`, { form });
      router.push(`/import/${created.id}`);
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      setDuplicate(status === 409);
      setError(e instanceof ApiError ? e.message : "Upload failed.");
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setDuplicate(false);
    void upload(false);
  }

  function onPick(f: File | null) {
    setError(null);
    setDuplicate(false);
    if (f && !f.name.toLowerCase().endsWith(".pdf")) {
      setFile(null);
      setError("Please choose a PDF file.");
      return;
    }
    if (f && f.size > MAX_MB * 1024 * 1024) {
      setFile(null);
      setError(`That file is larger than ${MAX_MB} MB.`);
      return;
    }
    setFile(f);
  }

  return (
    <>
      <PageHeader title="Import customers" subtitle="Upload the Wasooli PDF. Nothing is added until you review and confirm." />

      {can("import.upload") && (
        <Card title="Upload a Wasooli PDF">
          <form onSubmit={onSubmit}>
            <div className="toolbar">
              <input ref={fileInput} type="file" accept="application/pdf,.pdf" aria-label="Wasooli PDF"
                onChange={(e) => onPick(e.target.files?.[0] ?? null)} />
              <button className="btn" type="submit" disabled={!file || busy}>
                {busy ? "Uploading…" : "Upload and check"}
              </button>
            </div>
            {file ? <p className="small muted">{file.name} · {fmtBytes(file.size)}</p> : null}
            <p className="small muted">
              The file is read and checked first, which takes about half a minute for 1,250 customers.
            </p>
          </form>
          {error ? (
            <Notice kind={duplicate ? "warn" : "error"}>
              {error}{" "}
              {duplicate ? (
                <button className="btn secondary small" disabled={busy} onClick={() => void upload(true)}>
                  Upload anyway
                </button>
              ) : null}
            </Notice>
          ) : null}
        </Card>
      )}

      <Card title="Previous uploads">
        {sessions.error ? <ErrorBox message={sessions.error} onRetry={sessions.reload} /> : null}
        {sessions.loading && !sessions.data ? <Loading /> : null}
        {sessions.data && sessions.data.length === 0 ? <p className="muted">Nothing uploaded yet.</p> : null}
        {sessions.data && sessions.data.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>File</th><th>Uploaded</th><th>Rows</th><th>Status</th></tr></thead>
              <tbody>
                {sessions.data.map((s) => (
                  <tr key={s.id}>
                    <td><Link href={`/import/${s.id}`}>{s.file_name}</Link>
                      <div className="small muted">{fmtBytes(s.file_size)}</div></td>
                    <td>{fmtDateTime(s.created_at)}</td>
                    <td>{summaryView(s.summary).totalRows || ""}</td>
                    <td><StatusBadge status={s.status} label={SESSION_LABEL[s.status]} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
    </>
  );
}
