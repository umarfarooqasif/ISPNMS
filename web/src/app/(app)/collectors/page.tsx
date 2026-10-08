"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Card, ErrorBox, Loading, Notice, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import type { CollectorRow, UserRow } from "@/lib/types";

export default function CollectorsPage() {
  const collectors = useFetch<CollectorRow[]>("/collectors");
  const users = useFetch<UserRow[]>("/users");
  const [userId, setUserId] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const taken = new Set((collectors.data ?? []).map((c) => c.user_id));
  const candidates = (users.data ?? []).filter((u) => u.is_active && u.role_codes.includes("collector") && !taken.has(u.id));

  async function add() {
    if (!userId || !code.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api("/collectors", { json: { user_id: userId, code: code.trim().toUpperCase() } });
      setUserId(""); setCode("");
      collectors.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not add the collector.");
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(c: CollectorRow, status: "ACTIVE" | "INACTIVE") {
    const verb = status === "INACTIVE" ? "Deactivate" : "Reactivate";
    if (!window.confirm(`${verb} collector ${c.code}${c.full_name ? ` (${c.full_name})` : ""}?${status === "INACTIVE" ? "\n\nTheir phone will no longer be able to download customers or upload payments." : ""}`)) return;
    try {
      await api(`/collectors/${c.id}`, { method: "PATCH", json: { status } });
      collectors.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not change the collector.");
    }
  }

  return (
    <>
      <PageHeader title="Collectors" subtitle="People who collect payments in the field with the phone app." />
      <Card title="Add a collector">
        <p className="small muted">First create the person under Users with the &ldquo;Collector&rdquo; role, then add them here with a short code such as C01.</p>
        {users.error ? <Notice kind="info">Could not load the user list ({users.error}). Ask an administrator to add collectors.</Notice> : null}
        <div className="toolbar">
          <select aria-label="User" value={userId} onChange={(e) => setUserId(e.target.value)}>
            <option value="">Choose a user…</option>
            {candidates.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.username})</option>)}
          </select>
          <input type="text" placeholder="Code, e.g. C01" aria-label="Collector code" value={code}
            onChange={(e) => setCode(e.target.value)} style={{ width: 150 }} maxLength={32} />
          <button className="btn" disabled={busy || !userId || !code.trim()} onClick={() => void add()}>Add collector</button>
        </div>
        {users.data && candidates.length === 0 ? <p className="small muted">No user with the Collector role is waiting to be added.</p> : null}
        {error ? <Notice kind="error">{error}</Notice> : null}
      </Card>

      <Card>
        {collectors.error ? <ErrorBox message={collectors.error} onRetry={collectors.reload} /> : null}
        {collectors.loading && !collectors.data ? <Loading /> : null}
        {collectors.data && collectors.data.length === 0 ? <p className="muted">No collectors yet.</p> : null}
        {collectors.data && collectors.data.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Code</th><th>Person</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {collectors.data.map((c) => (
                  <tr key={c.id}>
                    <td className="mono"><strong>{c.code}</strong></td>
                    <td>{c.full_name ?? "—"}<div className="small muted">{c.username}</div></td>
                    <td>{c.status === "ACTIVE" ? <Badge tone="green">active</Badge> : <Badge tone="red">inactive</Badge>}</td>
                    <td>
                      <div className="actions">
                        <Link className="btn secondary small" href={`/collectors/${c.id}`}>Customers and areas</Link>
                        {c.status === "ACTIVE"
                          ? <button className="btn secondary small" onClick={() => void setStatus(c, "INACTIVE")}>Deactivate</button>
                          : <button className="btn secondary small" onClick={() => void setStatus(c, "ACTIVE")}>Reactivate</button>}
                      </div>
                    </td>
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
