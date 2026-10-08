"use client";

import { useState } from "react";

import { Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { qs } from "@/lib/api";
import { auditHighlights, describeAction, redact } from "@/lib/adminview";
import { fmtDateTime } from "@/lib/format";
import { useDebounced, useFetch } from "@/lib/hooks";
import type { AuditEntry, UserRow } from "@/lib/types";

const PAGE = 50;

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [userId, setUserId] = useState("");
  const daction = useDebounced(action, 400).trim();
  const key = `${daction}|${userId}`;
  const [pageState, setPageState] = useState({ key, page: 0 });
  const page = pageState.key === key ? pageState.page : 0;

  const users = useFetch<UserRow[]>("/users");
  const log = useFetch<AuditEntry[]>(`/audit-logs${qs({ action: daction, user_id: userId, limit: PAGE + 1, offset: page * PAGE })}`);
  const rows = (log.data ?? []).slice(0, PAGE);
  const hasNext = (log.data?.length ?? 0) > PAGE;
  const who = (id: string | null) => (id ? users.data?.find((u) => u.id === id)?.full_name ?? `user ${id.slice(0, 8)}` : "system");

  return (
    <>
      <PageHeader title="Audit log" subtitle="A permanent record of who did what. Entries cannot be edited or deleted." />
      <Card>
        <div className="toolbar">
          <input type="search" placeholder="Filter by action, e.g. payment.void" aria-label="Action" value={action}
            onChange={(e) => setAction(e.target.value)} style={{ minWidth: 260 }} />
          <select aria-label="User" value={userId} onChange={(e) => setUserId(e.target.value)}>
            <option value="">Everyone</option>
            {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </select>
        </div>
        {log.error ? <ErrorBox message={log.error} onRetry={log.reload} /> : null}
        {log.loading && !log.data ? <Loading /> : null}
        {log.data && rows.length === 0 ? <p className="muted">Nothing matches.</p> : null}
        {rows.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id}>
                    <td style={{ whiteSpace: "nowrap" }}>{fmtDateTime(e.at)}</td>
                    <td>{who(e.user_id)}</td>
                    <td>{describeAction(e.action)}<div className="small muted mono">{e.action}</div></td>
                    <td className="small">
                      {auditHighlights(e).join(" · ")}
                      <details><summary>All details</summary>
                        <pre className="raw">{JSON.stringify(redact({ before: e.before, after: e.after, ip: e.ip, entity: e.entity, entity_id: e.entity_id }), null, 2)}</pre>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <div className="pager">
          <button className="btn secondary small" disabled={page === 0} onClick={() => setPageState({ key, page: page - 1 })}>← Newer</button>
          <span className="muted small">Page {page + 1}</span>
          <button className="btn secondary small" disabled={!hasNext} onClick={() => setPageState({ key, page: page + 1 })}>Older →</button>
        </div>
      </Card>
    </>
  );
}
