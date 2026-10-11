"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { refundBody, refundProblem } from "@/lib/adjustview";
import { money } from "@/lib/format";
import { Card, Notice } from "./ui";

/** Pays back advance credit the customer actually has. Never more than the credit. */
export function RefundCredit({ customerId, customerName, credit, onDone }: {
  customerId: string;
  customerName: string;
  credit: string;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState(credit.replace(/\.00$/, ""));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const problem = refundProblem(amount, reason, credit);
  const started = reason.trim() !== "";

  async function save() {
    if (problem || busy) return;
    if (!window.confirm(`Pay ${money(amount.trim())} back to ${customerName}?\n\nThis is money going out and cannot be undone from this screen.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api("/refunds", { json: refundBody(customerId, amount, reason) });
      setDone(`Refund of ${money(amount.trim())} recorded.`);
      setReason("");
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record the refund.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={`Pay back credit (${money(credit)} available)`}>
      {done ? <Notice kind="ok">{done}</Notice> : null}
      <div className="toolbar">
        <input type="text" inputMode="decimal" placeholder="Amount (Rs)" aria-label="Refund amount" value={amount}
          onChange={(e) => setAmount(e.target.value)} style={{ width: 150 }} />
        <input type="text" placeholder="Reason (required)" aria-label="Reason" value={reason}
          onChange={(e) => setReason(e.target.value)} style={{ flex: "1 1 220px" }} />
        <button className="btn" disabled={busy || !!problem} onClick={() => void save()}>{busy ? "Saving…" : "Record refund"}</button>
      </div>
      {started && problem ? <Notice kind="warn">{problem}</Notice> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
    </Card>
  );
}
