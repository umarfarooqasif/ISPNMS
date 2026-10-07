"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { api, ApiError } from "@/lib/api";
import { amountProblem, METHOD_LABEL, OFFICE_METHODS } from "@/lib/billingview";
import { money } from "@/lib/format";
import type { Payment } from "@/lib/types";
import { Card, Notice } from "./ui";

/** Records a payment received at the office. Real money: it asks you to confirm the amount first. */
export function RecordPayment({ customerId, customerName, onDone }: {
  customerId: string;
  customerName: string;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("CASH");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Payment | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const problem = amountProblem(amount);
    if (problem) { setError(problem); return; }
    const label = METHOD_LABEL[method] ?? method;
    if (!window.confirm(`Record ${money(amount.trim())} (${label}) received from ${customerName}?`)) return;

    setBusy(true);
    setError(null);
    try {
      const p = await api<Payment>("/payments", {
        json: { customer_id: customerId, amount: amount.trim(), method, notes: notes.trim() || null },
      });
      setSaved(p);
      setAmount("");
      setNotes("");
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not record the payment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Record a payment">
      {saved ? (
        <Notice kind="ok">
          Recorded {money(saved.amount)}. Receipt{" "}
          <Link href={`/payments/${saved.id}`}><strong>{saved.receipt_number ?? "(none)"}</strong></Link>.{" "}
          {Number(saved.unallocated) > 0 ? <>{money(saved.unallocated)} was kept as advance credit. </> : null}
          Balance now: {Number(saved.balance) < 0 ? `credit ${money(saved.balance.slice(1))}` : money(saved.balance) || "Rs 0"}.
        </Notice>
      ) : null}
      <form onSubmit={submit}>
        <div className="toolbar">
          <input type="text" inputMode="decimal" placeholder="Amount (Rs)" aria-label="Amount" value={amount}
            onChange={(e) => setAmount(e.target.value)} style={{ width: 150 }} />
          <select aria-label="Payment method" value={method} onChange={(e) => setMethod(e.target.value)}>
            {OFFICE_METHODS.map((m) => <option key={m} value={m}>{METHOD_LABEL[m]}</option>)}
          </select>
          <input type="text" placeholder="Note (optional)" aria-label="Note" value={notes}
            onChange={(e) => setNotes(e.target.value)} style={{ flex: "1 1 200px" }} />
          <button className="btn" type="submit" disabled={busy}>{busy ? "Saving…" : "Record payment"}</button>
        </div>
      </form>
      {error ? <Notice kind="error">{error}</Notice> : null}
      <p className="small muted">
        The payment settles the oldest unpaid bill first. Anything extra is kept as advance credit.
      </p>
    </Card>
  );
}
