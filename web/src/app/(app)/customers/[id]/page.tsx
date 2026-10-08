"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { AddConnection } from "@/components/AddConnection";
import { ConnectionStatus } from "@/components/ConnectionStatus";
import { EditCustomer } from "@/components/EditCustomer";
import { RecordPayment } from "@/components/RecordPayment";
import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice, PageHeader, Stat, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { METHOD_LABEL } from "@/lib/billingview";
import { fmtDate, fmtDateTime, isPositiveMoney, money } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import type { Area, Connection, Customer, Payment, Statement } from "@/lib/types";

export default function CustomerPage() {
  const { id } = useParams<{ id: string }>();
  const customer = useFetch<Customer>(`/customers/${id}`);
  const connections = useFetch<Connection[]>(`/customers/${id}/connections`);
  const statement = useFetch<Statement>(`/customers/${id}/statement`);
  const areas = useFetch<Area[]>("/areas");
  const can = useCan();
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const payments = useFetch<Payment[]>(can("payment.view") ? `/payments?customer_id=${id}&limit=10` : null);

  if (customer.loading && !customer.data) return <Loading />;
  if (!customer.data) return <ErrorBox message={customer.error ?? "Customer not found."} onRetry={customer.reload} />;
  const c = customer.data;
  const area = areas.data?.find((a) => a.id === c.area_id);
  const st = statement.data;

  async function archive() {
    if (!window.confirm(`Archive ${c.full_name}?\n\nThey disappear from the customer list and are no longer billed. Their history is kept.`)) return;
    setArchiveError(null);
    try {
      await api(`/customers/${c.id}/archive`, { method: "POST" });
      customer.reload();
    } catch (e) {
      setArchiveError(e instanceof ApiError ? e.message : "Could not archive.");
    }
  }

  return (
    <>
      <p className="small"><Link href="/customers">← All customers</Link></p>
      <PageHeader
        title={c.full_name}
        subtitle={<><span className="mono">{c.customer_code}</span>{" "}<StatusBadge status={c.status} />{" "}
          {st?.billing_status ? <StatusBadge status={st.billing_status} /> : null}</>}
        actions={
          <div className="actions">
            {can("customer.update") && c.status !== "ARCHIVED" ? <button className="btn secondary" onClick={() => setEditing(!editing)}>Edit details</button> : null}
            {can("connection.create") && c.status !== "ARCHIVED" ? <button className="btn secondary" onClick={() => setAdding(!adding)}>Add connection</button> : null}
            {can("customer.archive") && c.status !== "ARCHIVED" ? <button className="btn secondary" onClick={() => void archive()}>Archive</button> : null}
          </div>
        }
      />
      {archiveError ? <Notice kind="error">{archiveError}</Notice> : null}
      {c.status === "ARCHIVED" ? <Notice kind="warn">This customer is archived. They are not billed and do not appear in the normal list.</Notice> : null}
      {editing ? <EditCustomer customer={c} areas={areas.data ?? []} onSaved={customer.reload} onClose={() => setEditing(false)} /> : null}
      {adding ? <AddConnection customerId={c.id} onSaved={() => { connections.reload(); statement.reload(); }} onClose={() => setAdding(false)} /> : null}
      {c.full_name_ur ? <p className="urdu" style={{ marginTop: "-.5rem" }}>{c.full_name_ur}</p> : null}

      <div className="stats">
        <Stat label="Balance" value={st ? (isPositiveMoney(st.balance) ? money(st.balance) : st.balance.startsWith("-") ? `Credit ${money(st.balance.slice(1))}` : "Rs 0") : "…"}
          hint={st && isPositiveMoney(st.balance) ? "owed" : undefined} />
        <Stat label="Amount due" value={st ? money(st.amount_due) : "…"} />
        <Stat label="Advance credit" value={st ? money(st.credit) : "…"} />
      </div>

      {can("payment.create") && c.status !== "ARCHIVED" ? (
        <RecordPayment customerId={c.id} customerName={c.full_name}
          onDone={() => { statement.reload(); payments.reload(); }} />
      ) : null}

      <div className="grid">
        <Card title="Details">
          <dl className="kv">
            <dt>Mobile</dt><dd>{c.mobile ?? "—"}</dd>
            {c.whatsapp && c.whatsapp !== c.mobile ? <><dt>WhatsApp</dt><dd>{c.whatsapp}</dd></> : null}
            {c.alt_contact ? <><dt>Other contact</dt><dd>{c.alt_contact}</dd></> : null}
            <dt>Area</dt><dd>{area?.name ?? "—"}</dd>
            <dt>House no</dt><dd>{c.house_no ?? "—"}</dd>
            <dt>Address</dt><dd>{c.address ?? "—"}{c.address_ur ? <div className="urdu">{c.address_ur}</div> : null}</dd>
            {c.father_name ? <><dt>Father</dt><dd>{c.father_name}</dd></> : null}
            {c.cnic_masked ? <><dt>CNIC</dt><dd>{c.cnic_masked}</dd></> : null}
            {c.notes ? <><dt>Notes</dt><dd>{c.notes}</dd></> : null}
          </dl>
        </Card>
      </div>

      <Card title="Connections">
        {connections.error ? <ErrorBox message={connections.error} onRetry={connections.reload} /> : null}
        {connections.loading && !connections.data ? <Loading /> : null}
        {connections.data && connections.data.length === 0 ? <p className="muted">No connections.</p> : null}
        {connections.data && connections.data.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Code</th><th>Internet ID</th><th>Type</th><th>Status</th><th>Monthly</th><th>Next due</th>{can("connection.status") ? <th></th> : null}</tr>
              </thead>
              <tbody>
                {connections.data.map((k) => {
                  const lines = k.service_lines.map((l) => `${l.service.toLowerCase()} ${money(l.price)}`.trim()).join(" + ");
                  return (
                    <tr key={k.id}>
                      <td className="mono">{k.connection_code}</td>
                      <td>{k.internet_id ?? k.username ?? "—"}</td>
                      <td>{k.connection_type.toLowerCase()}</td>
                      <td><StatusBadge status={k.status} /></td>
                      <td>
                        {k.monthly_price_override ? <>{money(k.monthly_price_override)} <span className="small muted">(special)</span></> : lines || "—"}
                      </td>
                      <td>{fmtDate(k.next_due_date) || <span className="muted">not set</span>}</td>
                      {can("connection.status") ? (
                        <td><ConnectionStatus connection={k} onChanged={() => { connections.reload(); statement.reload(); }} /></td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      {can("payment.view") ? (
        <Card title="Recent payments">
          {payments.error ? <ErrorBox message={payments.error} onRetry={payments.reload} /> : null}
          {payments.loading && !payments.data ? <Loading /> : null}
          {payments.data && payments.data.length === 0 ? <p className="muted">No payments yet.</p> : null}
          {payments.data && payments.data.length > 0 ? (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Date</th><th>Receipt</th><th>Method</th><th className="right">Amount</th><th>Status</th></tr></thead>
                <tbody>
                  {payments.data.map((p) => (
                    <tr key={p.id}>
                      <td>{fmtDateTime(p.collected_at)}</td>
                      <td><Link href={`/payments/${p.id}`}>{p.receipt_number ?? "view"}</Link></td>
                      <td>{METHOD_LABEL[p.method] ?? p.method}</td>
                      <td className="right">{money(p.amount)}</td>
                      <td><StatusBadge status={p.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </Card>
      ) : null}

      <Card title="Unpaid bills">
        {statement.error ? <ErrorBox message={statement.error} onRetry={statement.reload} /> : null}
        {statement.loading && !statement.data ? <Loading /> : null}
        {st && st.open_invoices.length === 0 ? <p className="muted">No unpaid bills.</p> : null}
        {st && st.open_invoices.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Invoice</th><th>For month</th><th>Due</th><th className="right">Total</th><th className="right">Paid</th><th className="right">Owed</th><th>Status</th></tr>
              </thead>
              <tbody>
                {st.open_invoices.map((i) => (
                  <tr key={i.id}>
                    <td className="mono">{i.invoice_number}</td>
                    <td>{i.period ? fmtDate(i.period).replace(/^\d+ /, "") : "—"}</td>
                    <td>{fmtDate(i.due_date)}</td>
                    <td className="right">{money(i.total)}</td>
                    <td className="right">{money(i.paid)}</td>
                    <td className="right"><strong>{money(i.outstanding)}</strong></td>
                    <td><StatusBadge status={i.status} /></td>
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
