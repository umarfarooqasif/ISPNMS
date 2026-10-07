"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, Notice, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { parseOpeningBalanceCsv } from "@/lib/billingview";
import { money, sumMoney } from "@/lib/format";
import type { OpeningBalanceLoad } from "@/lib/types";

const TONE: Record<string, "green" | "amber" | "red" | "blue"> = {
  CREATED: "green", WOULD_CREATE: "blue", ALREADY_EXISTS: "amber", NOT_FOUND: "red", INVALID: "red",
};
const LABEL: Record<string, string> = {
  CREATED: "loaded", WOULD_CREATE: "will be loaded", ALREADY_EXISTS: "already has one", NOT_FOUND: "customer not found", INVALID: "invalid",
};

export default function OpeningBalancesPage() {
  const can = useCan();
  const [text, setText] = useState("");
  const [asOf, setAsOf] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<{ result: OpeningBalanceLoad; text: string; asOf: string } | null>(null);
  const [loaded, setLoaded] = useState<OpeningBalanceLoad | null>(null);

  const parsed = useMemo(() => parseOpeningBalanceCsv(text), [text]);
  const fresh = checked !== null && checked.text === text && checked.asOf === asOf;
  const total = sumMoney(parsed.rows.map((r) => r.amount));

  async function send(dry: boolean) {
    setBusy(true);
    setError(null);
    try {
      const r = await api<OpeningBalanceLoad>("/billing/opening-balances", {
        json: { rows: parsed.rows, dry_run: dry, ...(asOf ? { as_of_date: asOf } : {}) },
      });
      if (dry) { setChecked({ result: r, text, asOf }); setLoaded(null); } else { setLoaded(r); setChecked(null); }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function load() {
    if (!fresh) return;
    const n = checked!.result.counts["WOULD_CREATE"] ?? 0;
    if (!window.confirm(`Load ${n} opening balance(s)?\n\nEach becomes a normal unpaid bill. This cannot be undone from this screen.`)) return;
    await send(false);
  }

  const view = loaded ?? (fresh ? checked!.result : null);
  const canLoad = fresh && (checked!.result.counts["WOULD_CREATE"] ?? 0) > 0;

  return (
    <>
      <PageHeader title="Opening balances (optional)"
        subtitle="Carry over what customers already owed before this system. Skip this page if you are starting fresh." />
      <Card title="Paste your list">
        <p className="small muted">
          One customer per line, with a header row: <span className="mono">wasooli_id,amount,note</span> (the note is optional).
          Copy it from Excel or Google Sheets, or type it. Amounts are what the customer <strong>owes</strong>.
        </p>
        <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} aria-label="Opening balances"
          placeholder={"wasooli_id,amount,note\n9001,1500,old register\n9002,2300.50"}
          style={{ width: "100%", font: "inherit", padding: ".6rem", border: "1px solid #c9d1d9", borderRadius: 8 }} />
        <div className="toolbar" style={{ marginTop: ".5rem" }}>
          <label className="small muted">Balances as of <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
          <span className="small muted">{parsed.rows.length} valid line(s), {money(total)} in total</span>
        </div>
        {parsed.problems.length > 0 ? (
          <Notice kind="warn">
            {parsed.problems.length} line(s) have a problem and will be left out:
            <ul className="issues">
              {parsed.problems.slice(0, 8).map((p) => <li key={p.line}>Line {p.line}: {p.text}</li>)}
              {parsed.problems.length > 8 ? <li>…and {parsed.problems.length - 8} more</li> : null}
            </ul>
          </Notice>
        ) : null}
        {can("billing.opening_balance") ? (
          <div className="actions">
            <button className="btn secondary" disabled={busy || parsed.rows.length === 0} onClick={() => void send(true)}>
              {fresh ? "Check again" : "Check (changes nothing)"}
            </button>
            <button className="btn" disabled={busy || !canLoad} onClick={() => void load()}>Load balances</button>
          </div>
        ) : <Notice kind="warn">You do not have permission to load opening balances.</Notice>}
        {error ? <Notice kind="error">{error}</Notice> : null}
        {checked && !fresh ? <Notice kind="warn">You changed the list. Check it again before loading.</Notice> : null}
      </Card>

      {view ? (
        <Card title={loaded ? "Result" : "What would happen"}>
          <div className="chips" style={{ marginBottom: ".75rem" }}>
            {Object.entries(view.counts).map(([k, v]) => <Badge key={k} tone={TONE[k] ?? "gray"}>{LABEL[k] ?? k}: {v}</Badge>)}
          </div>
          {view.results.filter((r) => r.status !== "WOULD_CREATE" && r.status !== "CREATED").length > 0 ? (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Row</th><th>Customer ID</th><th>Result</th><th>Details</th></tr></thead>
                <tbody>
                  {view.results.filter((r) => r.status !== "WOULD_CREATE" && r.status !== "CREATED").slice(0, 100).map((r) => (
                    <tr key={r.index}>
                      <td>{r.index + 1}</td>
                      <td className="mono">{parsed.rows[r.index]?.wasooli_id ?? ""}</td>
                      <td><Badge tone={TONE[r.status] ?? "gray"}>{LABEL[r.status] ?? r.status}</Badge></td>
                      <td className="small">{r.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {loaded ? <p>Done. <Link href="/billing/outstanding">See who owes money</Link></p> : null}
        </Card>
      ) : null}
    </>
  );
}
