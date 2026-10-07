"use client";

import Link from "next/link";
import { useState } from "react";

import { RunItemsTable } from "@/components/RunItemsTable";
import { useCan } from "@/components/Shell";
import { Card, Notice, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { amountProblem, runHeadline } from "@/lib/billingview";
import { money } from "@/lib/format";
import type { RunResult } from "@/lib/types";

const wholeDays = (s: string) => s.trim() === "" || /^\d{1,2}$/.test(s.trim());

export default function LateFeesPage() {
  const can = useCan();
  const [amount, setAmount] = useState("");
  const [grace, setGrace] = useState("");
  const [due, setDue] = useState("");
  const [runDate, setRunDate] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ result: RunResult; key: string } | null>(null);
  const [done, setDone] = useState<RunResult | null>(null);

  const key = JSON.stringify([amount.trim(), grace.trim(), due.trim(), runDate]);
  const fresh = preview?.key === key;
  const problem =
    (amount.trim() !== "" && amountProblem(amount)) ||
    (!wholeDays(grace) && "Grace days must be a whole number.") ||
    (!wholeDays(due) && "Days to pay must be a whole number.") || null;

  function body(): Record<string, unknown> {
    const b: Record<string, unknown> = {};
    if (amount.trim()) b.amount = amount.trim();
    if (grace.trim()) b.grace_days = Number(grace);
    if (due.trim()) b.due_days = Number(due);
    if (runDate) b.run_date = runDate;
    return b;
  }

  async function post(path: string, extra: Record<string, unknown>) {
    setBusy(true);
    setError(null);
    try {
      return await api<RunResult>(path, { json: { ...body(), ...extra } });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function doPreview() {
    const r = await post("/billing/late-fees/preview", {});
    if (r) { setPreview({ result: r, key }); setAck(false); setDone(null); }
  }

  async function doRun() {
    if (!fresh || !ack) return;
    if (!window.confirm(`Charge late fees totalling ${money(preview!.result.total_billed)} to ${preview!.result.invoices_created} customer(s)?\n\nThis cannot be undone from this screen.`)) return;
    const r = await post("/billing/late-fees", { confirm: true });
    if (r) { setDone(r); setPreview(null); setAck(false); }
  }

  return (
    <>
      <PageHeader title="Late fees" subtitle="One flat fee per overdue bill, charged once. Always preview first." />
      {done ? (
        <Notice kind="ok">
          Done: {runHeadline(done, false)}, {money(done.total_billed)} charged.{" "}
          {done.run_id ? <Link href={`/billing/runs/${done.run_id}`}>See the record</Link> : null}
        </Notice>
      ) : null}
      <Card title="Settings">
        <div className="toolbar">
          <input type="text" inputMode="decimal" placeholder="Fee per bill (Rs)" aria-label="Fee" value={amount}
            onChange={(e) => setAmount(e.target.value)} style={{ width: 160 }} />
          <input type="text" inputMode="numeric" placeholder="Grace days" aria-label="Grace days" value={grace}
            onChange={(e) => setGrace(e.target.value)} style={{ width: 120 }} />
          <input type="text" inputMode="numeric" placeholder="Days to pay the fee" aria-label="Days to pay" value={due}
            onChange={(e) => setDue(e.target.value)} style={{ width: 170 }} />
          <label className="small muted">As of <input type="date" value={runDate} onChange={(e) => setRunDate(e.target.value)} /></label>
        </div>
        <p className="small muted">
          Leave a box empty to use the server&apos;s standard setting. Late fees are switched off until a fee amount is set
          (here, or by the administrator). The fee is never charged on a fee, on imported opening balances, or to customers
          who are fully disconnected.
        </p>
        {problem ? <Notice kind="warn">{problem}</Notice> : null}
        {can("billing.run") ? (
          <button className="btn" disabled={busy || !!problem} onClick={() => void doPreview()}>
            {fresh ? "Preview again" : "Preview (changes nothing)"}
          </button>
        ) : <Notice kind="warn">You do not have permission to run late fees.</Notice>}
        {error ? <Notice kind="error">{error}</Notice> : null}
      </Card>

      {preview ? (
        <Card title="Preview">
          {!fresh ? <Notice kind="warn">You changed the settings. Preview again before charging.</Notice> : null}
          {preview.result.items.length === 0 ? <p>No bill is late enough to be charged a fee.</p> : (
            <>
              <p><strong>{preview.result.invoices_created} customer(s)</strong> would be charged {money(preview.result.total_billed)} in total.</p>
              <RunItemsTable items={preview.result.items.slice(0, 200)} />
              {can("billing.run") ? (
                <div style={{ marginTop: "1rem" }}>
                  <label className="small">
                    <input type="checkbox" checked={ack} disabled={!fresh} onChange={(e) => setAck(e.target.checked)} />{" "}
                    I have read this preview and want to charge these fees
                  </label>
                  <div style={{ marginTop: ".5rem" }}>
                    <button className="btn" disabled={busy || !fresh || !ack} onClick={() => void doRun()}>Charge late fees now</button>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </Card>
      ) : null}
    </>
  );
}
