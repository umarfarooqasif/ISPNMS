"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { RunItemsTable } from "@/components/RunItemsTable";
import { Card, ErrorBox, Loading, PageHeader, Stat } from "@/components/ui";
import { qs } from "@/lib/api";
import { ATTENTION_OUTCOMES, OUTCOME_LABEL } from "@/lib/billingview";
import { fmtDate, fmtDateTime, money } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import type { BillingRunFull, RunItem } from "@/lib/types";

const PAGE = 100;

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const run = useFetch<BillingRunFull>(`/billing/runs/${id}`);
  const counts = run.data?.summary?.counts ?? {};
  const outcomes = [...ATTENTION_OUTCOMES, "INVOICED", "FREE_SKIPPED", "LATE_FEE"].filter((o) => (counts[o] ?? 0) > 0);
  const [choice, setChoice] = useState<string | null>(null);
  const outcome = choice ?? outcomes.find((o) => ATTENTION_OUTCOMES.includes(o)) ?? outcomes[0] ?? "";
  const [page, setPage] = useState({ outcome, n: 0 });
  const n = page.outcome === outcome ? page.n : 0;
  const items = useFetch<RunItem[]>(run.data ? `/billing/runs/${id}/items${qs({ outcome, limit: PAGE + 1, offset: n * PAGE })}` : null);
  const shown = (items.data ?? []).slice(0, PAGE);
  const hasNext = (items.data?.length ?? 0) > PAGE;

  if (run.loading && !run.data) return <Loading />;
  if (!run.data) return <ErrorBox message={run.error ?? "Run not found."} onRetry={run.reload} />;
  const r = run.data;

  return (
    <>
      <p className="small"><Link href="/billing/runs">← Billing history</Link></p>
      <PageHeader title={r.kind === "MONTHLY" ? "Monthly bill run" : "Late-fee run"}
        subtitle={`Done ${fmtDateTime(r.created_at)} · billing date ${fmtDate(r.run_date)}`} />
      <div className="stats">
        <Stat label="Invoices created" value={r.invoices_created.toLocaleString("en-US")} />
        <Stat label="Total billed" value={money(r.total_billed)} />
        {r.summary?.behind_connections ? <Stat label="Still behind" value={r.summary.behind_connections.toLocaleString("en-US")} hint="connections" /> : null}
        {r.summary?.skipped_cycles ? <Stat label="Months left out" value={r.summary.skipped_cycles.toLocaleString("en-US")} /> : null}
      </div>
      <Card title="What happened">
        <div className="tabs">
          {outcomes.map((o) => (
            <button key={o} className={`tab ${outcome === o ? "active" : ""}`} onClick={() => setChoice(o)}>
              {OUTCOME_LABEL[o] ?? o} ({counts[o]})
            </button>
          ))}
        </div>
        {outcomes.length === 0 ? <p className="muted">This run did not touch any customers.</p> : null}
        {items.error ? <ErrorBox message={items.error} onRetry={items.reload} /> : null}
        {items.loading && !items.data ? <Loading /> : null}
        {items.data ? <RunItemsTable items={shown} /> : null}
        {outcomes.length > 0 ? (
          <div className="pager">
            <button className="btn secondary small" disabled={n === 0} onClick={() => setPage({ outcome, n: n - 1 })}>← Previous</button>
            <span className="muted small">Page {n + 1}</span>
            <button className="btn secondary small" disabled={!hasNext} onClick={() => setPage({ outcome, n: n + 1 })}>Next →</button>
          </div>
        ) : null}
      </Card>
    </>
  );
}
