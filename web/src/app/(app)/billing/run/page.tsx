"use client";

import Link from "next/link";
import { useState } from "react";

import { RunItemsTable } from "@/components/RunItemsTable";
import { useCan } from "@/components/Shell";
import { Card, Notice, PageHeader, Stat } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import {
  ATTENTION_OUTCOMES, OUTCOME_LABEL, itemsByOutcome, paramsKey, runHeadline, runParamsProblem, toRunBody,
  type RunParams,
} from "@/lib/billingview";
import { money } from "@/lib/format";
import type { RunResult } from "@/lib/types";

export default function BillRunPage() {
  const can = useCan();
  const [runDate, setRunDate] = useState("");
  const [leadDays, setLeadDays] = useState("");
  const [maxCycles, setMaxCycles] = useState(1);
  const [skipRemaining, setSkipRemaining] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [filter, setFilter] = useState("");

  const [preview, setPreview] = useState<{ result: RunResult; key: string } | null>(null);
  const [done, setDone] = useState<RunResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const params: RunParams = { runDate, leadDays, maxCycles, skipRemaining };
  const key = paramsKey(params);
  const problem = runParamsProblem(params);
  const fresh = preview !== null && preview.key === key;

  async function call<T>(path: string, body: Record<string, unknown>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await api<T>(path, { json: body });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function runPreview() {
    if (problem) return;
    const r = await call<RunResult>("/billing/runs/preview", toRunBody(params));
    if (r) { setPreview({ result: r, key }); setAcknowledged(false); setFilter(""); setDone(null); }
  }

  async function execute() {
    if (!fresh || !acknowledged) return;
    const n = preview!.result.invoices_created;
    if (!window.confirm(`Create ${n.toLocaleString("en-US")} real invoice(s) for ${money(preview!.result.total_billed)}?\n\nThis cannot be undone from this screen.`)) return;
    const r = await call<RunResult>("/billing/runs", { ...toRunBody(params), confirm: true });
    if (r) { setDone(r); setPreview(null); setAcknowledged(false); }
  }

  const shown = preview ? itemsByOutcome(preview.result.items, filter) : [];
  const counts = preview?.result.counts ?? {};
  const outcomes = [...ATTENTION_OUTCOMES, "INVOICED", "FREE_SKIPPED"].filter((o) => (counts[o] ?? 0) > 0);

  return (
    <>
      <PageHeader title="Monthly bill run" subtitle="Creates this month's invoices. Always preview first." />

      {done ? (
        <Notice kind={done.counts["ERROR"] ? "warn" : "ok"}>
          Done: {runHeadline(done, false)}, {money(done.total_billed)} billed.{" "}
          {done.run_id ? <Link href={`/billing/runs/${done.run_id}`}>See the full record</Link> : null}
        </Notice>
      ) : null}

      <Card title="Settings">
        <div className="grid">
          <div>
            <label className="small muted" htmlFor="rd">Billing date (leave empty for today)</label><br />
            <input id="rd" type="date" value={runDate} onChange={(e) => setRunDate(e.target.value)} />
          </div>
          <div>
            <label className="small muted" htmlFor="ld">Bill this many days ahead (empty = standard setting)</label><br />
            <input id="ld" type="text" inputMode="numeric" placeholder="e.g. 5" value={leadDays}
              onChange={(e) => setLeadDays(e.target.value)} style={{ width: 120 }} />
          </div>
          <div>
            <label className="small muted" htmlFor="mc">Months to bill per customer in this run</label><br />
            <select id="mc" value={maxCycles} onChange={(e) => setMaxCycles(Number(e.target.value))}>
              {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
        </div>
        <label style={{ display: "block", marginTop: ".75rem" }}>
          <input type="checkbox" checked={skipRemaining} onChange={(e) => setSkipRemaining(e.target.checked)} />{" "}
          Leave out any older months beyond that (for customers who are many months behind)
        </label>
        <p className="small muted">
          Customers whose due date is long past would otherwise be billed one month per run. For your <strong>first</strong> run,
          choose 1 month and tick the box above: each customer gets one month and the older months are listed, not billed.
        </p>
        {problem ? <Notice kind="warn">{problem}</Notice> : null}
        {can("billing.run") ? (
          <button className="btn" disabled={busy || !!problem} onClick={() => void runPreview()}>
            {busy && !preview ? "Working…" : fresh ? "Preview again" : "Preview (changes nothing)"}
          </button>
        ) : <Notice kind="warn">You do not have permission to run billing.</Notice>}
        {error ? <Notice kind="error">{error}</Notice> : null}
      </Card>

      {preview && (
        <Card title="Preview">
          {!fresh ? <Notice kind="warn">You changed the settings. Preview again before billing.</Notice> : null}
          <p><strong>{runHeadline(preview.result, true)}</strong>, totalling {money(preview.result.total_billed)}.</p>
          <div className="stats">
            {outcomes.map((o) => (
              <Stat key={o} label={OUTCOME_LABEL[o] ?? o} value={(counts[o] ?? 0).toLocaleString("en-US")} />
            ))}
          </div>
          {(counts["ZERO_PRICE"] ?? 0) + (counts["NO_DUE_DATE"] ?? 0) > 0 ? (
            <Notice kind="warn">
              Customers marked &ldquo;not billed&rdquo; will be skipped until you fix their price or due date. Nothing is lost:
              they appear again in the next run.
            </Notice>
          ) : null}
          <div className="tabs">
            <button className={`tab ${filter === "" ? "active" : ""}`} onClick={() => setFilter("")}>All</button>
            {outcomes.map((o) => (
              <button key={o} className={`tab ${filter === o ? "active" : ""}`} onClick={() => setFilter(o)}>
                {OUTCOME_LABEL[o] ?? o} ({counts[o]})
              </button>
            ))}
          </div>
          <RunItemsTable items={shown.slice(0, 200)} />
          {shown.length > 200 || preview.result.items_truncated ? (
            <p className="small muted">Showing the first 200. The full list is saved with the run once you bill.</p>
          ) : null}

          {can("billing.run") ? (
            <div style={{ marginTop: "1rem" }}>
              <label className="small">
                <input type="checkbox" checked={acknowledged} disabled={!fresh}
                  onChange={(e) => setAcknowledged(e.target.checked)} />{" "}
                I have read this preview and want to create these invoices
              </label>
              <div style={{ marginTop: ".5rem" }}>
                <button className="btn" disabled={busy || !fresh || !acknowledged || preview.result.invoices_created === 0}
                  onClick={() => void execute()}>
                  Create invoices now
                </button>
              </div>
            </div>
          ) : null}
        </Card>
      )}
    </>
  );
}
