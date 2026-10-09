"use client";

import { useParams } from "next/navigation";

import { CompanyHeader, PrintFrame, useCompany } from "@/components/Print";
import { ErrorBox, Loading } from "@/components/ui";
import { fmtDate, money } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import type { Customer, Invoice } from "@/lib/types";

export default function PrintInvoicePage() {
  const { id } = useParams<{ id: string }>();
  const company = useCompany();
  const inv = useFetch<Invoice & { customer_id: string; notes: string | null }>(`/invoices/${id}`);
  const cust = useFetch<Customer>(inv.data ? `/customers/${inv.data.customer_id}` : null);

  if (inv.loading && !inv.data) return <Loading />;
  if (!inv.data) return <ErrorBox message={inv.error ?? "Invoice not found."} onRetry={inv.reload} />;
  const i = inv.data;
  const c = cust.data;

  return (
    <PrintFrame backHref={`/customers/${i.customer_id}/history`} size="a4">
      <CompanyHeader company={company} />
      <div className="print-title" style={{ textAlign: "left", fontSize: "1.4em" }}>INVOICE {i.invoice_number}</div>
      <div className="print-row"><span>Issued</span><span>{fmtDate(i.issue_date)}</span></div>
      <div className="print-row"><span>Due</span><strong>{fmtDate(i.due_date)}</strong></div>
      {i.period ? <div className="print-row"><span>For the month of</span><span>{fmtDate(i.period).replace(/^\d+ /, "")}</span></div> : null}
      <div className="print-row"><span>Status</span><strong>{i.status}</strong></div>
      <div style={{ margin: ".8rem 0" }}>
        <strong>Bill to</strong>
        <div>{c?.full_name ?? ""} {c ? `(${c.customer_code})` : ""}</div>
        {c?.address ? <div>{c.address}</div> : null}
        {c?.mobile ? <div>{c.mobile}</div> : null}
      </div>
      <table>
        <thead><tr><th>Description</th><th className="r">Amount</th></tr></thead>
        <tbody>
          {i.lines.map((l) => <tr key={l.id}><td>{l.description ?? l.charge_type}</td><td className="r">{money(l.amount)}</td></tr>)}
          <tr><td className="r"><strong>Total</strong></td><td className="r"><strong>{money(i.total)}</strong></td></tr>
          <tr><td className="r">Paid</td><td className="r">{money(i.paid) || "Rs 0"}</td></tr>
          <tr><td className="r"><strong>Amount due</strong></td><td className="r"><strong>{money(i.outstanding) || "Rs 0"}</strong></td></tr>
        </tbody>
      </table>
      {i.notes ? <p className="small">{i.notes}</p> : null}
      <div className="print-foot">Thank you for your business.</div>
    </PrintFrame>
  );
}
