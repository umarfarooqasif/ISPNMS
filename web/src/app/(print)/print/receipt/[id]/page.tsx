"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { CompanyHeader, PrintFrame, useCompany, type PaperSize } from "@/components/Print";
import { ErrorBox, Loading } from "@/components/ui";
import { METHOD_LABEL } from "@/lib/billingview";
import { fmtDateTime, money, sumMoney } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import { balanceText, usageText } from "@/lib/history";
import type { Payment } from "@/lib/types";

export default function PrintReceiptPage() {
  const { id } = useParams<{ id: string }>();
  const company = useCompany();
  const pay = useFetch<Payment>(`/payments/${id}`);
  const [size, setSize] = useState<PaperSize>("80mm");

  if (pay.loading && !pay.data) return <Loading />;
  if (!pay.data) return <ErrorBox message={pay.error ?? "Receipt not found."} onRetry={pay.reload} />;
  const p = pay.data;
  const allocated = sumMoney(p.allocations.map((a) => a.amount));
  const voided = p.status === "VOID";

  return (
    <PrintFrame backHref={`/payments/${p.id}`} sizes={["80mm", "a4"]} size={size} onSize={setSize}>
      <CompanyHeader company={company} />
      <div className="print-title">PAYMENT RECEIPT{voided ? " (CANCELLED)" : ""}</div>
      <div className="print-big">{money(p.amount)}</div>
      <div className="print-row"><span>Receipt no</span><strong>{p.receipt_number ?? ""}</strong></div>
      {p.client_receipt_no ? <div className="print-row"><span>Paper receipt no</span><span>{p.client_receipt_no}</span></div> : null}
      <div className="print-row"><span>Date</span><span>{fmtDateTime(p.collected_at)}</span></div>
      <div className="print-row"><span>Customer</span><strong>{p.customer_name}</strong></div>
      <div className="print-row"><span>Customer ID</span><span>{p.customer_code}</span></div>
      <div className="print-row"><span>Method</span><span>{METHOD_LABEL[p.method] ?? p.method}</span></div>
      {!voided ? <div className="print-row"><span>Used for</span><span>{usageText(allocated, p.unallocated)}</span></div> : null}
      {!voided ? <div className="print-row"><span>Balance now</span><strong>{balanceText(p.balance)}</strong></div> : null}
      <div className="print-foot">Thank you. Please keep this receipt.</div>
    </PrintFrame>
  );
}
