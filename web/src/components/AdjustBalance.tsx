"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { KIND_LABEL, adjustBody, adjustProblem, balanceAfter, type AdjustKind } from "@/lib/adjustview";
import { money } from "@/lib/format";
import { Card, Notice } from "./ui";

/** Credits, discounts and extra charges. Recorded in the account history with your name and reason. */
export function AdjustBalance({ customerId, customerName, balance, onDone }: {
  customerId: string;
  customerName: string;
  balance: string;
  onDone: () => void;
}) {
  const [kind, setKind] = useState<AdjustKind>("credit");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const problem = adjustProblem(amount, reason);
  const started = amount.trim() !== "" || reason.trim() !== "";

  async function save() {
    if (problem || busy) return;
    const what = kind === "credit" ? "credit" : "extra charge";
    if (!window.confirm(`Record a ${money(amount.trim())} ${what} for ${customerName}?\n\nBalance afterwards: ${balanceAfter(balance, kind, amount)}.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api("/adjustments", { json: adjustBody(customerId, kind, amount, reason) });
      setDone(`Recorded. Balance is now ${balanceAfter(balance, kind, amount)}.`);
      setAmount("");
      setReason("");
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record the adjustment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Adjust the balance">
      {done ? <Notice kind="ok">{done}</Notice> : null}
      <div className="toolbar">
        <select aria-label="Type" value={kind} onChange={(e) => setKind(e.target.value as AdjustKind)}>
          {(Object.keys(KIND_LABEL) as AdjustKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
        </select>
        <input type="text" inputMode="decimal" placeholder="Amount (Rs)" aria-label="Amount" value={amount}
          onChange={(e) => setAmount(e.target.value)} style={{ width: 150 }} />
        <input type="text" placeholder="Reason (required)" aria-label="Reason" value={reason}
          onChange={(e) => setReason(e.target.value)} style={{ flex: "1 1 220px" }} />
        <button className="btn" disabled={busy || !!problem} onClick={() => void save()}>{busy ? "Saving…" : "Record"}</button>
      </div>
      {started && problem ? <Notice kind="warn">{problem}</Notice> : null}
      {!problem ? <p className="small">Balance afterwards: <strong>{balanceAfter(balance, kind, amount)}</strong></p> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <p className="small muted">
        A credit lowers what the customer owes. Their old bills stay in the list until paid, but nothing more is
        charged for them: no late fee is added while the account is in credit. To cancel a mistaken payment,
        open it under Payments instead.
      </p>
    </Card>
  );
}
