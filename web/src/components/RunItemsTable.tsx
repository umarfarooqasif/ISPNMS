import Link from "next/link";

import { fmtDate, money } from "@/lib/format";
import { OUTCOME_LABEL, outcomeNeedsAttention } from "@/lib/billingview";
import type { RunItem } from "@/lib/types";
import { Badge } from "./ui";

export function RunItemsTable({ items }: { items: RunItem[] }) {
  if (items.length === 0) return <p className="muted">Nothing here.</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>Customer</th><th>Result</th><th>For</th><th className="right">Amount</th><th>Details</th></tr></thead>
        <tbody>
          {items.map((i, n) => (
            <tr key={`${i.customer_id}-${i.connection_id ?? ""}-${i.cycle_due_date ?? ""}-${n}`}>
              <td>
                <Link href={`/customers/${i.customer_id}`}>{i.customer_name ?? "customer"}</Link>
                <div className="small muted">{i.customer_code}</div>
              </td>
              <td>
                <Badge tone={outcomeNeedsAttention(i.outcome) ? "amber" : i.outcome === "INVOICED" ? "green" : "gray"}>
                  {OUTCOME_LABEL[i.outcome] ?? i.outcome}
                </Badge>
              </td>
              <td>{fmtDate(i.cycle_due_date)}</td>
              <td className="right">{i.amount && Number(i.amount) > 0 ? money(i.amount) : ""}</td>
              <td className="small">{i.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
