"use client";

import Link from "next/link";
import { useState } from "react";

import { Card, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { qs } from "@/lib/api";
import { fmtDate, fmtDateTime, money } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import type { BillingRunFull } from "@/lib/types";

const PAGE = 20;

export default function RunsPage() {
  const [page, setPage] = useState(0);
  const list = useFetch<BillingRunFull[]>(`/billing/runs${qs({ limit: PAGE + 1, offset: page * PAGE })}`);
  const rows = (list.data ?? []).slice(0, PAGE);
  const hasNext = (list.data?.length ?? 0) > PAGE;

  return (
    <>
      <PageHeader title="Billing history" subtitle="Every bill run and late-fee run, newest first."
        actions={<Link className="btn" href="/billing/run">New bill run</Link>} />
      <Card>
        {list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> : null}
        {list.loading && !list.data ? <Loading /> : null}
        {list.data && rows.length === 0 ? <p className="muted">No runs yet.</p> : null}
        {rows.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Done</th><th>Type</th><th>Billing date</th><th className="right">Invoices</th><th className="right">Total</th><th></th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtDateTime(r.created_at)}</td>
                    <td><StatusBadge status={r.kind === "MONTHLY" ? "ACTIVE" : "DUE"} label={r.kind === "MONTHLY" ? "monthly bill run" : "late fees"} /></td>
                    <td>{fmtDate(r.run_date)}</td>
                    <td className="right">{r.invoices_created.toLocaleString("en-US")}</td>
                    <td className="right">{money(r.total_billed)}</td>
                    <td><Link href={`/billing/runs/${r.id}`}>Details</Link></td>
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
    </>
  );
}
