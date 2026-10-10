"use client";

import Link from "next/link";

import { useCan, useMe } from "@/components/Shell";
import { BarChart, GroupedBarChart, HBars } from "@/components/Charts";
import { Card, ErrorBox, Loading, PageHeader, Stat, StatusBadge } from "@/components/ui";
import { fmtDate, fmtDateTime, money } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import { SESSION_LABEL } from "@/lib/importview";
import type { BillingRun, Dashboard, ImportSession, OutstandingRow } from "@/lib/types";

export default function DashboardPage() {
  const me = useMe();
  const can = useCan();
  const outstanding = useFetch<OutstandingRow[]>(can("invoice.view") ? "/billing/outstanding?limit=5" : null);
  const imports = useFetch<ImportSession[]>(can("import.upload") ? "/imports" : null);
  const runs = useFetch<BillingRun[]>(can("invoice.view") ? "/billing/runs?limit=1" : null);
  const dash = useFetch<Dashboard>(can("report.view") ? "/reports/dashboard" : null);
  const lastImport = imports.data?.[0];
  const lastRun = runs.data?.[0];

  return (
    <>
      <PageHeader title={`Welcome, ${me.full_name}`} subtitle="Here is where things stand." />

      {can("report.view") ? <Numbers dash={dash} /> : null}

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

const num = (s: string) => Number(s);
const monthName = (iso: string) => ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(iso.slice(5, 7)) - 1];

function Numbers({ dash }: { dash: { data: Dashboard | null; error: string | null; loading: boolean; reload: () => void } }) {
  if (dash.error) return <ErrorBox message={dash.error} onRetry={dash.reload} />;
  if (!dash.data) return <Loading text="Loading the numbers…" />;
  const d = dash.data;
  const status = d.connections_by_status;
  return (
    <>
      <div className="stats">
        <Stat label="Collected today" value={money(d.today_collected) || "Rs 0"} hint={`${d.today_payments} payment(s)`} />
        <Stat label={`Billed in ${monthName(d.month_label + "-01")}`} value={money(d.month_billed) || "Rs 0"} />
        <Stat label="Collected this month" value={money(d.month_collected) || "Rs 0"}
          hint={d.collection_rate ? `${d.collection_rate}% of billed` : `${d.month_payments} payment(s)`} />
        <Stat label="Owed by customers" value={money(d.outstanding_total) || "Rs 0"} hint={`${d.outstanding_customers.toLocaleString("en-US")} customer(s)`} />
        <Stat label="Active connections" value={(status["ACTIVE"] ?? 0).toLocaleString("en-US")}
          hint={`${(status["DISCONNECTED"] ?? 0).toLocaleString("en-US")} disconnected`} />
      </div>
      <div className="grid">
        <Card title="Collections, last 30 days">
          <BarChart label="Money collected each day over the last 30 days"
            data={d.daily.map((x) => ({ label: x.day.slice(8), value: num(x.total), detail: `${x.day}: ${money(x.total) || "Rs 0"} (${x.count} payment(s))` }))} />
        </Card>
        <Card title="Billed and collected, last 12 months">
          <GroupedBarChart label="Money billed and money collected for each of the last 12 months" names={["Billed", "Collected"]}
            data={d.monthly.map((m) => ({ label: monthName(m.month), a: num(m.billed), b: num(m.collected),
              detail: `${monthName(m.month)} ${m.month.slice(0, 4)}: billed ${money(m.billed) || "Rs 0"}, collected ${money(m.collected) || "Rs 0"}` }))} />
          <p className="small muted">Balances carried over from the old system are not counted as billed.</p>
        </Card>
        <Card title="Collections by collector this month">
          {d.collectors_this_month.length === 0 ? <p className="muted">No payments yet this month.</p> : (
            <table className="table"><tbody>
              {d.collectors_this_month.map((c) => (
                <tr key={c.collector_id ?? "office"}>
                  <td><strong>{c.code}</strong> <span className="small muted">{c.name}</span></td>
                  <td className="right">{c.count} payment(s)</td>
                  <td className="right"><strong>{money(c.total)}</strong></td>
                </tr>
              ))}
            </tbody></table>
          )}
        </Card>
        <Card title="Where the money is owed">
          <HBars rows={d.outstanding_by_area.map((a) => ({ label: a.area, value: num(a.total), text: money(a.total), sub: `${a.customers} customer(s)` }))} />
        </Card>
      </div>
    </>
  );
}
