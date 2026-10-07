"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, ErrorBox, Loading, Notice, PageHeader, Stat, StatusBadge } from "@/components/ui";
import { api, ApiError, qs } from "@/lib/api";
import { fmtBytes, fmtDateTime, money, plural } from "@/lib/format";
import { useDebounced, useFetch } from "@/lib/hooks";
import {
  ACTION_LABEL, STATUS_LABEL, SESSION_LABEL, attachableCustomers, candidateText, canCommit,
  commitWarnings, defaultRowStatus, isBusy, issueLabel, rowField, rowName, summaryView,
} from "@/lib/importview";
import type { CommitResult, Decision, ImportRow, ImportSession } from "@/lib/types";

const PAGE = 50;
const TABS = ["REVIEW", "ERROR", "NEW", "UPDATED", "DUPLICATE", "IMPORTED", "SKIPPED"];
type Msg = { kind: "ok" | "error" | "warn" | "info"; text: string };

export default function ImportSessionPage() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const session = useFetch<ImportSession>(`/imports/${id}`, (d) => (d && isBusy(d.status) ? 2000 : null));

  const s = session.data;
  const view = summaryView(s?.summary);
  const ready = !!s && !isBusy(s.status) && s.status !== "FAILED";

  // ---- rows panel
  const [tabChoice, setTabChoice] = useState<string | null>(null);
  const tab = tabChoice ?? defaultRowStatus(view.rowsByStatus);
  const [issue, setIssue] = useState("");
  const [search, setSearch] = useState("");
  const dsearch = useDebounced(search, 300).trim();
  const rowsKey = `${tab}|${issue}|${dsearch}`;
  const [pageState, setPageState] = useState({ key: rowsKey, page: 0 });
  const page = pageState.key === rowsKey ? pageState.page : 0;
  const rows = useFetch<ImportRow[]>(
    ready ? `/imports/${id}/rows${qs({ status: tab, issue, q: dsearch, limit: PAGE + 1, offset: page * PAGE })}` : null,
  );
  const shown = (rows.data ?? []).slice(0, PAGE);
  const hasNext = (rows.data?.length ?? 0) > PAGE;

  // ---- decisions and messages
  const [decided, setDecided] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<Msg | null>(null);
  const [working, setWorking] = useState(false);

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setWorking(true);
    setMsg(null);
    try {
      return await fn();
    } catch (e) {
      setMsg({ kind: "error", text: e instanceof ApiError ? e.message : "Something went wrong." });
      return undefined;
    } finally {
      setWorking(false);
    }
  }

  async function decide(row: ImportRow, decision: Decision, label: string, editedValues?: Record<string, unknown>) {
    const ok = await run(() =>
      api(`/imports/${id}/rows/${row.id}/decision`, { json: { decision, edited_values: editedValues ?? null } }),
    );
    if (ok !== undefined) setDecided((d) => ({ ...d, [row.id]: label }));
  }

  async function bulk(status: "NEW" | "REVIEW" | "UPDATED", decision: Decision, what: string) {
    const count = view.rowsByStatus[status] ?? 0;
    if (!window.confirm(`${what}\n\nThis applies to ${plural(count, "row")}.`)) return;
    const r = await run(() => api<{ rows_decided: number }>(`/imports/${id}/decisions/bulk`, { json: { status, decision } }));
    if (r) setMsg({ kind: "ok", text: `Saved your decision for ${plural(r.rows_decided, "row")}.` });
  }

  // ---- commit
  const [includeReview, setIncludeReview] = useState(false);
  const [preview, setPreview] = useState<{ result: CommitResult; include: boolean } | null>(null);
  const [done, setDone] = useState<CommitResult | null>(null);
  const previewValid = preview !== null && preview.include === includeReview;

  async function runPreview() {
    const r = await run(() => api<CommitResult>(`/imports/${id}/commit`, { json: { dry_run: true, include_review: includeReview } }));
    if (r) setPreview({ result: r, include: includeReview });
  }

  async function runCommit() {
    if (!previewValid) return;
    const planned = (preview!.result.actions["create"] ?? 0) + (preview!.result.actions["attach"] ?? 0) + (preview!.result.actions["update"] ?? 0);
    if (!window.confirm(`Import now?\n\n${plural(planned, "row")} will be added or updated. This cannot be undone from this screen.`)) return;
    const r = await run(() => api<CommitResult>(`/imports/${id}/commit`, { json: { dry_run: false, include_review: includeReview } }));
    if (r) {
      setDone(r);
      setPreview(null);
      session.reload();
      rows.reload();
    }
  }

  if (session.loading && !session.data) return <Loading />;
  if (!s) return <ErrorBox message={session.error ?? "Import not found."} onRetry={session.reload} />;

  const warnings = commitWarnings(previewValid ? preview!.result : null);
  const reviewCount = view.rowsByStatus["REVIEW"] ?? 0;

  return (
    <>
      <p className="small"><Link href="/import">← All imports</Link></p>
      <PageHeader
        title={s.file_name}
        subtitle={<>{fmtBytes(s.file_size)} · uploaded {fmtDateTime(s.created_at)}{" "}
          <StatusBadge status={s.status} label={SESSION_LABEL[s.status]} /></>}
      />

      {isBusy(s.status) ? <Notice kind="info">{SESSION_LABEL[s.status]} This page updates by itself.</Notice> : null}
      {s.status === "FAILED" ? (
        <Notice kind="error">The file could not be processed{view.error ? `: ${view.error}` : "."} You can upload it again.</Notice>
      ) : null}
      {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
      {done ? (
        <Notice kind={done.result?.["failed"] ? "warn" : "ok"}>
          Import finished: {plural(done.result?.["customers_created"] ?? 0, "customer")} created,{" "}
          {plural(done.result?.["connections_attached"] ?? 0, "connection")} attached,{" "}
          {plural(done.result?.["updated"] ?? 0, "connection")} updated
          {done.result?.["failed"] ? `, ${done.result["failed"]} failed (see the rows below)` : ""}.{" "}
          <Link href="/customers">View customers</Link>
        </Notice>
      ) : null}

      {ready && (
        <>
          <div className="stats">
            <Stat label="Rows in the file" value={view.totalRows.toLocaleString("en-US")} />
            {TABS.filter((t) => (view.rowsByStatus[t] ?? 0) > 0).map((t) => (
              <Stat key={t} label={STATUS_LABEL[t] ?? t} value={(view.rowsByStatus[t] ?? 0).toLocaleString("en-US")} />
            ))}
            {view.monthlyChargeTotal ? <Stat label="Monthly charges in file" value={money(view.monthlyChargeTotal)} /> : null}
          </div>

          <div className="grid">
            <Card title="What the file contains">
              <dl className="kv">
                {Object.entries(view.connectionStatus).map(([k, v]) => (
                  <Fragment key={`s-${k}`}><dt>{k.toLowerCase()}</dt><dd>{v.toLocaleString("en-US")}</dd></Fragment>
                ))}
                {Object.entries(view.connectionType).map(([k, v]) => (
                  <Fragment key={`t-${k}`}><dt>{String(k).toLowerCase()} connections</dt><dd>{v.toLocaleString("en-US")}</dd></Fragment>
                ))}
              </dl>
              {view.areasToCreate.length > 0 ? (
                <p className="small"><strong>{view.areasToCreate.length} new area(s):</strong> {view.areasToCreate.join(", ")}</p>
              ) : null}
              {view.packagesToCreate.length > 0 ? (
                <p className="small"><strong>New packages:</strong> {view.packagesToCreate.map(([n, c]) => `${n} (${c})`).join(", ")}</p>
              ) : null}
            </Card>

            <Card title="Things worth a look">
              {view.issueCounts.length === 0 ? <p className="muted">Nothing unusual found.</p> : (
                <div className="chips">
                  {view.issueCounts.map(([code, n]) => (
                    <button key={code} className={`chip ${issue === code ? "active" : ""}`}
                      title="Show only these rows"
                      onClick={() => setIssue(issue === code ? "" : code)}>
                      {issueLabel(code)} · {n}
                    </button>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <Card title="Rows"
            actions={can("import.review") && reviewCount > 0 ? (
              <div className="actions">
                <button className="btn secondary small" disabled={working}
                  onClick={() => void bulk("REVIEW", "CREATE_SEPARATE", "Import ALL possible duplicates as separate customers?")}>
                  Import all possible duplicates
                </button>
                <button className="btn secondary small" disabled={working}
                  onClick={() => void bulk("REVIEW", "SKIP", "Skip ALL possible duplicates?")}>
                  Skip all possible duplicates
                </button>
              </div>
            ) : undefined}>
            <div className="tabs" role="tablist">
              {TABS.filter((t) => (view.rowsByStatus[t] ?? 0) > 0).map((t) => (
                <button key={t} role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "active" : ""}`}
                  onClick={() => setTabChoice(t)}>
                  {STATUS_LABEL[t] ?? t} ({view.rowsByStatus[t]})
                </button>
              ))}
            </div>
            <div className="toolbar">
              <input type="search" placeholder="Search name, ID, Internet ID or mobile…" value={search}
                aria-label="Search rows" onChange={(e) => setSearch(e.target.value)} />
              {issue ? (
                <button className="chip active" onClick={() => setIssue("")}>{issueLabel(issue)} ✕</button>
              ) : null}
            </div>
            {tab === "REVIEW" ? (
              <p className="small muted">
                These rows look like someone who is already in the system or elsewhere in this file. Decide for each:
                import as a new customer, attach to the existing one, or skip. Rows you do not decide are left out.
                Decisions are saved on the server; this page marks only the ones you make during this visit.
              </p>
            ) : null}

            {rows.error ? <ErrorBox message={rows.error} onRetry={rows.reload} /> : null}
            {rows.loading && !rows.data ? <Loading /> : null}
            {rows.data && shown.length === 0 ? <p className="muted">No rows here.</p> : null}

            {shown.length > 0 ? (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>#</th><th>Customer</th><th>Mobile</th><th>Area</th><th className="right">Monthly</th><th>Notes</th>
                    {can("import.review") ? <th>Decision</th> : null}</tr></thead>
                  <tbody>
                    {shown.map((r) => {
                      const issues = r.issues ?? [];
                      const attach = attachableCustomers(r);
                      return (
                        <tr key={r.id}>
                          <td className="muted">{r.row_index}</td>
                          <td>
                            <strong>{rowName(r)}</strong>
                            <div className="small muted">ID {rowField(r, "wasooli_id") || r.raw_cells?.["ID"] || "?"}</div>
                            <details><summary>Show file data</summary>
                              <pre className="raw">{JSON.stringify(r.raw_cells, null, 2)}</pre>
                            </details>
                          </td>
                          <td>{rowField(r, "mobile") || <span className="muted">none</span>}</td>
                          <td>{rowField(r, "area")}</td>
                          <td className="right">{money(rowField(r, "total"))}</td>
                          <td>
                            {issues.length > 0 ? (
                              <ul className="issues">
                                {issues.slice(0, 3).map((i) => <li key={i.code} className={i.severity}>{i.message}</li>)}
                                {issues.length > 3 ? <li className="muted">+{issues.length - 3} more</li> : null}
                              </ul>
                            ) : null}
                            {(r.match_candidates ?? []).filter((c) => c.kind === "customer" || c.kind === "same_file").map((c, n) => (
                              <div key={n} className="small"><Badge tone="amber">possible duplicate</Badge> {candidateText(c)}</div>
                            ))}
                          </td>
                          {can("import.review") ? (
                            <td>
                              {decided[r.id] ? <Badge tone="blue">{decided[r.id]}</Badge> : null}
                              {!decided[r.id] && (r.status === "REVIEW" || r.status === "NEW") ? (
                                <div className="actions">
                                  <button className="btn small" disabled={working}
                                    onClick={() => void decide(r, r.status === "REVIEW" ? "CREATE_SEPARATE" : "IMPORT", "will import")}>
                                    Import as new
                                  </button>
                                  {attach.map((c) => (
                                    <button key={c.customer_id} className="btn secondary small" disabled={working}
                                      onClick={() => void decide(r, "UPDATE_EXISTING", `attach to ${c.customer_code}`, { customer_id: c.customer_id })}>
                                      Attach to {c.customer_code}
                                    </button>
                                  ))}
                                  <button className="btn secondary small" disabled={working}
                                    onClick={() => void decide(r, "SKIP", "will skip")}>Skip</button>
                                </div>
                              ) : null}
                            </td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}

            <div className="pager">
              <button className="btn secondary small" disabled={page === 0}
                onClick={() => setPageState({ key: rowsKey, page: page - 1 })}>← Previous</button>
              <span className="muted small">Page {page + 1}</span>
              <button className="btn secondary small" disabled={!hasNext}
                onClick={() => setPageState({ key: rowsKey, page: page + 1 })}>Next →</button>
            </div>
          </Card>

          {can("import.commit") && canCommit(s) ? (
            <Card title="Import the customers">
              <p>
                First <strong>preview</strong> what would happen. Nothing is changed until you press
                &ldquo;Import now&rdquo; and confirm.
              </p>
              <label className="small" style={{ display: "block", marginBottom: ".75rem" }}>
                <input type="checkbox" checked={includeReview}
                  onChange={(e) => setIncludeReview(e.target.checked)} />{" "}
                Also import the {reviewCount} possible duplicate(s) I did not decide, as separate customers
              </label>
              <div className="actions">
                <button className="btn secondary" disabled={working} onClick={() => void runPreview()}>
                  {previewValid ? "Preview again" : "Preview"}
                </button>
                <button className="btn" disabled={working || !previewValid} onClick={() => void runCommit()}>
                  Import now
                </button>
              </div>

              {previewValid ? (
                <div style={{ marginTop: "1rem" }}>
                  <h2>What would happen</h2>
                  <dl className="kv" style={{ marginTop: ".5rem" }}>
                    {Object.entries(preview!.result.actions).map(([k, v]) => (
                      <Fragment key={k}><dt>{ACTION_LABEL[k] ?? k}</dt><dd>{v.toLocaleString("en-US")}</dd></Fragment>
                    ))}
                  </dl>
                  {warnings.map((w) => <Notice key={w} kind="info">{w}</Notice>)}
                </div>
              ) : preview ? (
                <p className="small muted" style={{ marginTop: ".75rem" }}>You changed the option: preview again before importing.</p>
              ) : (
                <p className="small muted" style={{ marginTop: ".75rem" }}>Press Preview to enable the import button.</p>
              )}
            </Card>
          ) : null}
        </>
      )}
    </>
  );
}
