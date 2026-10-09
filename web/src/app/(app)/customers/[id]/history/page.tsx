"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Card, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { qs } from "@/lib/api";
import { fmtDate, fmtDateTime, money } from "@/lib/format";
import { balanceText, columns, entryLabel } from "@/lib/history";
import { useFetch } from "@/lib/hooks";
import type { Customer, Invoice, LedgerRow, Statement } from "@/lib/types";

const PAGE = 25;

export default function CustomerHistoryPage() {
  const { id } = useParams<{ id: string }>();
  const customer = useFetch<Customer>(`/customers/${id}`);
  const statement = useFetch<Statement>(`/customers/${id}/statement`);
  const [tab, setTab] = useState<"ledger" | "bills">("ledger");

  if (customer.loading && !customer.data) return <Loading />;
  if (!customer.data) return <ErrorBox message={customer.error ?? "Customer not found."} onRetry={customer.reload} />;
  const c = customer.data;

  return (
    <>
      <p className="small"><Link href={`/customers/${id}`}>← {c.full_name}</Link></p>
      <PageHeader title="Account history"
        subtitle={<>{c.full_name} <span className="mono">{c.customer_code}</span>{statement.data ? <> · <strong>{balanceText(statement.data.balance)}</strong></> : null}</>}
        actions={<Link className="btn secondary" href={`/print/statement/${id}`}>Print statement</Link>} />
      <div className="tabs">
        <button className={`tab ${tab === "ledger" ? "active" : ""}`} onClick={() => setTab("ledger")}>Every entry</button>
        <button className={`tab ${tab === "bills" ? "active" : ""}`} onClick={() => setTab("bills")}>Bills</button>
      </div>
      {tab === "ledger" ? <Ledger id={id} /> : <Bills id={id} />}
    </>
  );
}

function Ledger({ id }: { id: string }) {
  const [page, setPage] = useState(0);
  const list = useFetch<LedgerRow[]>(`/customers/${id}/ledger${qs({ limit: PAGE + 1, offset: page * PAGE })}`);
  const rows = (list.data ?? []).slice(0, PAGE);
  const hasNext = (list.data?.length ?? 0) > PAGE;
  return (
    <Card>
      {list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> : null}
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && rows.length === 0 ? <p className="muted">Nothing has been billed or paid yet.</p> : null}
      {rows.length > 0 ? (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Date</th><th>Entry</th><th className="right">Charged</th><th className="right">Paid / credited</th><th className="right">Balance after</th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const col = columns(r.amount);
                const link = r.ref_type === "PAYMENT" && r.ref_id ? `/payments/${r.ref_id}` : r.ref_type === "INVOICE" && r.ref_id ? `/print/invoice/${r.ref_id}` : null;
                return (
                  <tr key={r.id}>
                    <td>{fmtDateTime(r.posted_at)}</td>
                    <td>
                      {entryLabel(r.entry_type)} {r.reference ? (link ? <Link href={link}>{r.reference}</Link> : r.reference) : null}
                      {r.description ? <div className="small muted">{r.description}</div> : null}
                    </td>
                    <td className="right">{col.charged}</td>
                    <td className="right">{col.credited}</td>
                    <td className="right"><strong>{balanceText(r.balance)}</strong></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="pager">
        <button className="btn secondary small" disabled={page === 0} onClick={() => setPage(page - 1)}>← Newer</button>
        <span className="muted small">Page {page + 1}</span>
        <button className="btn secondary small" disabled={!hasNext} onClick={() => setPage(page + 1)}>Older →</button>
      </div>
    </Card>
  );
}

function Bills({ id }: { id: string }) {
  const [page, setPage] = useState(0);
  const list = useFetch<Invoice[]>(`/customers/${id}/invoices${qs({ limit: PAGE + 1, offset: page * PAGE })}`);
  const rows = (list.data ?? []).slice(0, PAGE);
  const hasNext = (list.data?.length ?? 0) > PAGE;
  return (
    <Card>
      {list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> : null}
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && rows.length === 0 ? <p className="muted">No bills yet.</p> : null}
      {rows.length > 0 ? (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Bill</th><th>Month</th><th>Due</th><th className="right">Total</th><th className="right">Paid</th><th className="right">Owed</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id}>
                  <td className="mono">{i.invoice_number}</td>
                  <td>{i.period ? fmtDate(i.period).replace(/^\d+ /, "") : ""}</td>
                  <td>{fmtDate(i.due_date)}</td>
                  <td className="right">{money(i.total)}</td>
                  <td className="right">{money(i.paid) || "Rs 0"}</td>
                  <td className="right"><strong>{money(i.outstanding) || "Rs 0"}</strong></td>
                  <td><StatusBadge status={i.status} /></td>
                  <td><Link href={`/print/invoice/${i.id}`}>Print</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="pager">
        <button className="btn secondary small" disabled={page === 0} onClick={() => setPage(page - 1)}>← Newer</button>
        <span className="muted small">Page {page + 1}</span>
        <button className="btn secondary small" disabled={!hasNext} onClick={() => setPage(page + 1)}>Older →</button>
      </div>
    </Card>
  );
}
