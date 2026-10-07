"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice, PageHeader, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { METHOD_LABEL } from "@/lib/billingview";
import { fmtDateTime, money, sumMoney } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import type { Payment } from "@/lib/types";

export default function PaymentPage() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const pay = useFetch<Payment>(`/payments/${id}`);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  if (pay.loading && !pay.data) return <Loading />;
  if (!pay.data) return <ErrorBox message={pay.error ?? "Payment not found."} onRetry={pay.reload} />;
  const p = pay.data;
  const voided = p.status === "VOID";

  async function voidIt() {
    if (reason.trim().length < 3) { setError("Please explain why (at least 3 characters)."); return; }
    if (!window.confirm(`Cancel this payment of ${money(p.amount)}?\n\nThe customer's bills become unpaid again. This cannot be undone.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api<Payment>(`/payments/${id}/void`, { json: { reason: reason.trim() } });
      setAsking(false);
      setReason("");
      pay.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not cancel the payment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="small"><Link href="/payments">← All payments</Link></p>
      <PageHeader
        title={`Receipt ${p.receipt_number ?? ""}`}
        subtitle={<><StatusBadge status={p.status} label={voided ? "cancelled" : "recorded"} /></>}
      />
      {voided ? <Notice kind="warn">This payment was cancelled{p.void_reason ? `: ${p.void_reason}` : ""}. It no longer counts.</Notice> : null}

      <Card>
        <dl className="kv">
          <dt>Amount</dt><dd><strong>{money(p.amount)}</strong></dd>
          <dt>Customer</dt>
          <dd><Link href={`/customers/${p.customer_id}`}>{p.customer_name ?? "customer"}</Link> <span className="muted">{p.customer_code}</span></dd>
          <dt>Method</dt><dd>{METHOD_LABEL[p.method] ?? p.method}</dd>
          <dt>Collected</dt><dd>{fmtDateTime(p.collected_at)}</dd>
          <dt>Recorded</dt><dd>{fmtDateTime(p.received_at)}</dd>
          {p.client_receipt_no ? <><dt>Paper receipt no</dt><dd className="mono">{p.client_receipt_no}</dd></> : null}
          <dt>Used for bills</dt><dd>{money(sumMoney(p.allocations.map((a) => a.amount)))}
            {p.allocations.length > 0 ? ` across ${p.allocations.length} bill(s)` : ""}</dd>
          {Number(p.unallocated) > 0 ? <><dt>Kept as credit</dt><dd>{money(p.unallocated)}</dd></> : null}
        </dl>
      </Card>

      {can("payment.void") && !voided ? (
        <Card title="Cancel this payment">
          {!asking ? (
            <button className="btn secondary" onClick={() => setAsking(true)}>Cancel this payment…</button>
          ) : (
            <>
              <p className="small muted">Only do this for a mistake. Say why; it is recorded with your name.</p>
              <div className="toolbar">
                <input type="text" placeholder="Reason" aria-label="Reason" value={reason}
                  onChange={(e) => setReason(e.target.value)} style={{ flex: "1 1 280px" }} />
                <button className="btn danger" disabled={busy} onClick={() => void voidIt()}>{busy ? "Cancelling…" : "Cancel payment"}</button>
                <button className="btn secondary" disabled={busy} onClick={() => { setAsking(false); setError(null); }}>Keep it</button>
              </div>
              {error ? <Notice kind="error">{error}</Notice> : null}
            </>
          )}
        </Card>
      ) : null}
    </>
  );
}
