"use client";

import Link from "next/link";
import { useState } from "react";

import { Card, ErrorBox, Loading, Notice, PageHeader, StatusBadge } from "@/components/ui";
import { qs } from "@/lib/api";
import { fmtDate, money } from "@/lib/format";
import { useDebounced, useFetch } from "@/lib/hooks";
import type { Area, OutstandingRow, SuspensionCandidate } from "@/lib/types";

const PAGE = 25;

export default function OutstandingPage() {
  const [area, setArea] = useState("");
  const [min, setMin] = useState("");
  const dmin = useDebounced(min, 400).trim();
  const minOk = dmin === "" || /^\d{1,10}(\.\d{1,2})?$/.test(dmin);
  const key = `${area}|${dmin}`;
  const [pageState, setPageState] = useState({ key, page: 0 });
  const page = pageState.key === key ? pageState.page : 0;

  const areas = useFetch<Area[]>("/areas");
  const list = useFetch<OutstandingRow[]>(
    minOk ? `/billing/outstanding${qs({ area_id: area, min_balance: dmin, limit: PAGE + 1, offset: page * PAGE })}` : null,
  );
  const rows = (list.data ?? []).slice(0, PAGE);
  const hasNext = (list.data?.length ?? 0) > PAGE;

  const [days, setDays] = useState("30");
  const late = useFetch<SuspensionCandidate[]>(`/billing/suspension-candidates?overdue_days=${days}`);

  return (
    <>
      <PageHeader title="Who owes money" subtitle="Customers with an unpaid balance, biggest first." />
      <Card>
        <div className="toolbar">
          <select value={area} aria-label="Area" onChange={(e) => setArea(e.target.value)}>
            <option value="">All areas</option>
            {(areas.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <input type="text" inputMode="decimal" placeholder="Owes at least (Rs)" aria-label="Minimum balance"
            value={min} onChange={(e) => setMin(e.target.value)} style={{ width: 170 }} />
        </div>
        {!minOk ? <Notice kind="warn">Enter the minimum as plain digits, for example 1000.</Notice> : null}
        {list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> : null}
        {list.loading && !list.data ? <Loading /> : null}
        {list.data && rows.length === 0 ? <p className="muted">Nobody matches. Either nobody owes money, or no bills have been created yet.</p> : null}
        {rows.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Customer</th><th>Mobile</th><th className="right">Owes</th><th>Oldest bill due</th><th className="right">Days late</th><th>Status</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.customer_id}>
                    <td><Link href={`/customers/${r.customer_id}`}>{r.full_name}</Link><div className="small muted">{r.customer_code}</div></td>
                    <td>{r.mobile ?? <span className="muted">none</span>}</td>
                    <td className="right"><strong>{money(r.balance)}</strong></td>
                    <td>{fmtDate(r.oldest_due_date)}</td>
                    <td className="right">{r.days_overdue > 0 ? r.days_overdue : ""}</td>
                    <td><StatusBadge status={r.billing_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <div className="pager">
          <button className="btn secondary small" disabled={page === 0} onClick={() => setPageState({ key, page: page - 1 })}>← Previous</button>
          <span className="muted small">Page {page + 1}</span>
          <button className="btn secondary small" disabled={!hasNext} onClick={() => setPageState({ key, page: page + 1 })}>Next →</button>
        </div>
      </Card>

      <Card title="Long overdue"
        actions={
          <select value={days} aria-label="Days overdue" onChange={(e) => setDays(e.target.value)}>
            {["15", "30", "60", "90"].map((d) => <option key={d} value={d}>more than {d} days late</option>)}
          </select>
        }>
        <p className="small muted">
          These customers still have an active connection. This list only shows who to follow up with. Nothing is ever
          suspended automatically.
        </p>
        {late.error ? <ErrorBox message={late.error} onRetry={late.reload} /> : null}
        {late.loading && !late.data ? <Loading /> : null}
        {late.data && late.data.length === 0 ? <p className="muted">Nobody is that late.</p> : null}
        {late.data && late.data.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Customer</th><th>Oldest bill due</th><th className="right">Days late</th><th className="right">Owes</th></tr></thead>
              <tbody>
                {late.data.map((c) => (
                  <tr key={c.customer_id}>
                    <td><Link href={`/customers/${c.customer_id}`}>{c.full_name}</Link></td>
                    <td>{fmtDate(c.oldest_due_date)}</td>
                    <td className="right">{c.days_overdue}</td>
                    <td className="right"><strong>{money(c.outstanding)}</strong></td>
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
