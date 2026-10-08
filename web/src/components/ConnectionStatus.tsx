"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { statusChangeBody, statusChangeProblem, statusChoices, type TargetStatus } from "@/lib/adminview";
import { money } from "@/lib/format";
import type { Connection, ConnectionStatusResult } from "@/lib/types";
import { Notice } from "./ui";

/** Suspend, disconnect or reactivate one connection, with a reason (audited) and an optional fee. */
export function ConnectionStatus({ connection, onChanged }: { connection: Connection; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const choices = statusChoices(connection.status);
  const [target, setTarget] = useState<TargetStatus>(choices[0].status);
  const [reason, setReason] = useState("");
  const [fee, setFee] = useState("");
  const [nextDue, setNextDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const problem = statusChangeProblem({ current: connection.status, target, reason, fee, nextDue });
  const reconnecting = target === "ACTIVE" && (connection.status === "SUSPENDED" || connection.status === "DISCONNECTED");

  async function apply() {
    if (problem || busy) return;
    const label = choices.find((c) => c.status === target)?.label ?? target;
    if (!window.confirm(`${label} connection ${connection.connection_code}?`)) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<ConnectionStatusResult>(`/connections/${connection.id}/status`, { json: statusChangeBody({ target, reason, fee, nextDue }) });
      setResult(r.reconnection_invoice ? `Done. Reconnection fee ${money(r.reconnection_invoice.total)} added to the bill.` : "Done.");
      setOpen(false);
      setReason(""); setFee(""); setNextDue("");
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not change the status.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div>
        <button className="btn secondary small" onClick={() => { setOpen(true); setTarget(statusChoices(connection.status)[0].status); }}>Change status</button>
        {result ? <div className="small muted">{result}</div> : null}
      </div>
    );
  }
  return (
    <div style={{ minWidth: 260 }}>
      <select aria-label="New status" value={target} onChange={(e) => setTarget(e.target.value as TargetStatus)}>
        {choices.map((c) => <option key={c.status} value={c.status}>{c.label}</option>)}
      </select>
      <input type="text" placeholder="Reason (required)" aria-label="Reason" value={reason}
        onChange={(e) => setReason(e.target.value)} style={{ width: "100%", marginTop: ".35rem" }} />
      {reconnecting ? (
        <div className="toolbar" style={{ marginTop: ".35rem" }}>
          <input type="text" inputMode="decimal" placeholder="Reconnection fee (optional)" aria-label="Reconnection fee"
            value={fee} onChange={(e) => setFee(e.target.value)} style={{ width: 200 }} />
          <label className="small muted">Bill from <input type="date" value={nextDue} onChange={(e) => setNextDue(e.target.value)} /></label>
        </div>
      ) : null}
      {problem && reason ? <div className="small" style={{ color: "var(--red)" }}>{problem}</div> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="actions" style={{ marginTop: ".35rem" }}>
        <button className="btn small" disabled={busy || !!problem} onClick={() => void apply()}>{busy ? "Saving…" : "Apply"}</button>
        <button className="btn secondary small" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}
