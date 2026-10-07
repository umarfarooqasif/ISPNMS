"use client";

import Link from "next/link";

import { useCan, useMe } from "@/components/Shell";
import { Card, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { fmtDate, fmtDateTime, money } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import { SESSION_LABEL } from "@/lib/importview";
import type { BillingRun, ImportSession, OutstandingRow } from "@/lib/types";

export default function DashboardPage() {
  const me = useMe();
  const can = useCan();
  const outstanding = useFetch<OutstandingRow[]>(can("invoice.view") ? "/billing/outstanding?limit=5" : null);
  const imports = useFetch<ImportSession[]>(can("import.upload") ? "/imports" : null);
  const runs = useFetch<BillingRun[]>(can("invoice.view") ? "/billing/runs?limit=1" : null);
  const lastImport = imports.data?.[0];
  const lastRun = runs.data?.[0];

  return (
    <>
      <PageHeader title={`Welcome, ${me.full_name}`} subtitle="Here is where things stand." />

      <div className="grid">
        {can("invoice.view") && (
          <Card title="Biggest balances owed">
            {outstanding.loading && !outstanding.data ? <Loading /> : null}
            {outstanding.error ? <ErrorBox message={outstanding.error} onRetry={outstanding.reload} /> : null}
            {outstanding.data && outstanding.data.length === 0 ? (
              <p className="muted">Nobody owes anything right now.</p>
            ) : null}
            {outstanding.data && outstanding.data.length > 0 ? (
              <table className="table">
                <tbody>
                  {outstanding.data.map((r) => (
                    <tr key={r.customer_id}>
                      <td>
                        <Link href={`/customers/${r.customer_id}`}>{r.full_name}</Link>
                        <div className="small muted">{r.customer_code}</div>
                      </td>
                      <td className="right">
                        <strong>{money(r.balance)}</strong>
                        <div className="small">
                          <StatusBadge status={r.billing_status} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </Card>
        )}

        {can("invoice.view") && (
          <Card title="Last billing run">
            {runs.error ? <ErrorBox message={runs.error} onRetry={runs.reload} /> : null}
            {runs.loading && !runs.data ? <Loading /> : null}
            {runs.data && !lastRun ? (
              <p className="muted">No billing run yet. Billing screens arrive in the next update.</p>
            ) : null}
            {lastRun ? (
              <dl className="kv">
                <dt>Run date</dt><dd>{fmtDate(lastRun.run_date)}</dd>
                <dt>Invoices</dt><dd>{lastRun.invoices_created.toLocaleString("en-US")}</dd>
                <dt>Total billed</dt><dd>{money(lastRun.total_billed)}</dd>
              </dl>
            ) : null}
          </Card>
        )}

        {can("import.upload") && (
          <Card title="Customer import" actions={<Link className="btn secondary small" href="/import">Open</Link>}>
            {imports.error ? <ErrorBox message={imports.error} onRetry={imports.reload} /> : null}
            {imports.loading && !imports.data ? <Loading /> : null}
            {imports.data && !lastImport ? <p className="muted">No file uploaded yet.</p> : null}
            {lastImport ? (
              <>
                <div>
                  <Link href={`/import/${lastImport.id}`}>{lastImport.file_name}</Link>
                </div>
                <p className="small muted">{fmtDateTime(lastImport.created_at)}</p>
                <StatusBadge status={lastImport.status} label={SESSION_LABEL[lastImport.status]} />
              </>
            ) : null}
          </Card>
        )}
      </div>
    </>
  );
}
