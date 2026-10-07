"use client";

import Link from "next/link";
import { useState } from "react";

import { Card, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { qs } from "@/lib/api";
import { METHOD_LABEL } from "@/lib/billingview";
import { fmtDateTime, money, sumMoney } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import type { Payment } from "@/lib/types";

const PAGE = 25;

export default function PaymentsPage() {
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const key = `${status}|${from}|${to}`;
  const [pageState, setPageState] = useState({ key, page: 0 });
  const page = pageState.key === key ? pageState.page : 0;

  const list = useFetch<Payment[]>(
    `/payments${qs({ status, date_from: from, date_to: to, limit: PAGE + 1, offset: page * PAGE })}`,
  );
  const rows = (list.data ?? []).slice(0, PAGE);
  const hasNext = (list.data?.length ?? 0) > PAGE;
  const pageTotal = sumMoney(rows.filter((p) => p.status !== "VOID").map((p) => p.amount));

  return (
    <>
      <PageHeader title="Payments" subtitle="Every payment received, newest first." />
      <Card>
        <div className="toolbar">
          <select value={status} aria-label="Status" onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            <option value="POSTED">Recorded</option>
            <option value="VOID">Voided</option>
          </select>
          <label className="small muted">From <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label className="small muted">To <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          {(status || from || to) ? (
            <button className="btn secondary small" onClick={() => { setStatus(""); setFrom(""); setTo(""); }}>Clear</button>
          ) : null}
        </div>

        {list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> : null}
        {list.loading && !list.data ? <Loading /> : null}
        {list.data && rows.length === 0 ? <p className="muted">No payments found.</p> : null}

        {rows.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Date</th><th>Receipt</th><th>Customer</th><th>Method</th><th className="right">Amount</th><th>Status</th></tr></thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id}>
                    <td>{fmtDateTime(p.collected_at)}</td>
                    <td><Link href={`/payments/${p.id}`}>{p.receipt_number ?? "view"}</Link>
                      {p.client_receipt_no ? <div className="small muted mono">{p.client_receipt_no}</div> : null}</td>
                    <td><Link href={`/customers/${p.customer_id}`}>{p.customer_name ?? "customer"}</Link>
                      <div className="small muted">{p.customer_code}</div></td>
                    <td>{METHOD_LABEL[p.method] ?? p.method}</td>
                    <td className="right">{money(p.amount)}</td>
                    <td><StatusBadge status={p.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="pager">
          <button className="btn secondary small" disabled={page === 0}
            onClick={() => setPageState({ key, page: page - 1 })}>← Previous</button>
          <span className="muted small">
            Page {page + 1}{rows.length > 0 ? ` · this page: ${money(pageTotal)}` : ""}
          </span>
          <button className="btn secondary small" disabled={!hasNext}
            onClick={() => setPageState({ key, page: page + 1 })}>Next →</button>
        </div>
      </Card>
    </>
  );
}
