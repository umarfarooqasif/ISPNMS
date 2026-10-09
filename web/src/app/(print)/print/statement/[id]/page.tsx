"use client";

import { useParams } from "next/navigation";

import { CompanyHeader, PrintFrame, useCompany } from "@/components/Print";
import { ErrorBox, Loading } from "@/components/ui";
import { fmtDate, fmtDateTime } from "@/lib/format";
import { balanceText, columns, entryLabel } from "@/lib/history";
import { useFetch } from "@/lib/hooks";
import type { Customer, LedgerRow } from "@/lib/types";

const LIMIT = 100;

export default function PrintStatementPage() {
  const { id } = useParams<{ id: string }>();
  const company = useCompany();
  const cust = useFetch<Customer>(`/customers/${id}`);
  const ledger = useFetch<LedgerRow[]>(`/customers/${id}/ledger?limit=${LIMIT}`);

  if ((cust.loading && !cust.data) || (ledger.loading && !ledger.data)) return <Loading />;
  if (!cust.data || !ledger.data) return <ErrorBox message={cust.error ?? ledger.error ?? "Could not load the statement."} onRetry={() => { cust.reload(); ledger.reload(); }} />;
  const c = cust.data;
  const rows = [...ledger.data].reverse(); // oldest first, like a bank statement
  const current = ledger.data[0]?.balance ?? "0.00";

  return (
    <PrintFrame backHref={`/customers/${id}/history`} size="a4">
      <CompanyHeader company={company} />
      <div className="print-title" style={{ textAlign: "left", fontSize: "1.4em" }}>ACCOUNT STATEMENT</div>
      <div className="print-row"><span>Customer</span><strong>{c.full_name} ({c.customer_code})</strong></div>
      {c.mobile ? <div className="print-row"><span>Mobile</span><span>{c.mobile}</span></div> : null}
      <div className="print-row"><span>Printed</span><span>{fmtDateTime(new Date().toISOString())}</span></div>
      <div className="print-row"><span>Balance now</span><strong>{balanceText(current)}</strong></div>
      {ledger.data.length === LIMIT ? <p className="small">Showing the latest {LIMIT} entries.</p> : null}
      <table style={{ marginTop: ".6rem" }}>
        <thead><tr><th>Date</th><th>Entry</th><th className="r">Charged</th><th className="r">Paid / credited</th><th className="r">Balance</th></tr></thead>
        <tbody>
          {rows.map((r) => {
            const col = columns(r.amount);
            return (
              <tr key={r.id}>
                <td>{fmtDate(r.effective_date)}</td>
                <td>{entryLabel(r.entry_type)}{r.reference ? ` ${r.reference}` : ""}{r.description && r.entry_type !== "PAYMENT" ? <div className="small">{r.description}</div> : null}</td>
                <td className="r">{col.charged}</td>
                <td className="r">{col.credited}</td>
                <td className="r">{balanceText(r.balance)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </PrintFrame>
  );
}
