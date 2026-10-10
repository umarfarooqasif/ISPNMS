"use client";

import { useState } from "react";

import { BarChart } from "@/components/Charts";
import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice, PageHeader, Stat } from "@/components/ui";
import { qs } from "@/lib/api";
import { METHOD_LABEL } from "@/lib/billingview";
import { downloadFile } from "@/lib/download";
import { money, sumMoney } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import { EXPORTS, PRESETS, exportFilename, exportPath, localIsoDate, presetRange, rangeProblem, type ExportName, type Preset } from "@/lib/reportview";
import type { CollectorTotal, DayTotal, MethodTotal } from "@/lib/types";

export default function ReportsPage() {
  const can = useCan();
  const today = localIsoDate(new Date());
  const [from, setFrom] = useState(presetRange("month", today).from);
  const [to, setTo] = useState(today);
  const [active, setActive] = useState<Preset | null>("month");
  const problem = rangeProblem(from, to);
  const query = problem ? null : qs({ date_from: from, date_to: to });

  const daily = useFetch<DayTotal[]>(query === null ? null : `/reports/collections/daily${query}`);
  const methods = useFetch<MethodTotal[]>(query === null ? null : `/reports/collections/by-method${query}`);
  const collectors = useFetch<CollectorTotal[]>(query === null ? null : `/reports/collections/by-collector${query}`);

  const total = sumMoney((daily.data ?? []).map((d) => d.total));
  const count = (daily.data ?? []).reduce((n, d) => n + d.count, 0);

  const [busy, setBusy] = useState<ExportName | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  async function download(name: ExportName) {
    setBusy(name);
    setExportError(null);
    try {
      await downloadFile(exportPath(name, from, to), exportFilename(name, from, to));
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "Could not download.");
    } finally {
      setBusy(null);
    }
  }

  function pick(p: Preset) {
    const r = presetRange(p, today);
    setFrom(r.from);
    setTo(r.to);
    setActive(p);
  }

  return (
    <>
      <PageHeader title="Reports" subtitle="Money collected, and files you can open in Excel." />
      <Card title="Dates">
        <div className="tabs">
          {PRESETS.map((p) => (
            <button key={p.id} className={`tab ${active === p.id ? "active" : ""}`} onClick={() => pick(p.id)}>{p.label}</button>
          ))}
        </div>
        <div className="toolbar">
          <label className="small muted">From <input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setActive(null); }} /></label>
          <label className="small muted">To <input type="date" value={to} onChange={(e) => { setTo(e.target.value); setActive(null); }} /></label>
        </div>
        {problem ? <Notice kind="warn">{problem}</Notice> : null}
      </Card>

      {!problem && (
        <>
          <div className="stats">
            <Stat label="Collected" value={money(total) || "Rs 0"} />
            <Stat label="Payments" value={count.toLocaleString("en-US")} />
          </div>

          <Card title="Collected each day">
            {daily.error ? <ErrorBox message={daily.error} onRetry={daily.reload} /> : null}
            {daily.loading && !daily.data ? <Loading /> : null}
            {daily.data ? (
              <BarChart label="Money collected each day in the chosen dates"
                data={daily.data.map((d) => ({ label: d.day.slice(8), value: Number(d.total), detail: `${d.day}: ${money(d.total) || "Rs 0"} (${d.count} payment(s))` }))} />
            ) : null}
          </Card>

          <div className="grid">
            <Card title="By payment method">
              {methods.error ? <ErrorBox message={methods.error} onRetry={methods.reload} /> : null}
              {methods.data && methods.data.length === 0 ? <p className="muted">No payments in these dates.</p> : null}
              {methods.data && methods.data.length > 0 ? (
                <table className="table"><tbody>
                  {methods.data.map((m) => (
                    <tr key={m.method}><td>{METHOD_LABEL[m.method] ?? m.method}</td><td className="right">{m.count} payment(s)</td><td className="right"><strong>{money(m.total)}</strong></td></tr>
                  ))}
                </tbody></table>
              ) : null}
            </Card>
            <Card title="By collector">
              {collectors.error ? <ErrorBox message={collectors.error} onRetry={collectors.reload} /> : null}
              {collectors.data && collectors.data.length === 0 ? <p className="muted">No payments in these dates.</p> : null}
              {collectors.data && collectors.data.length > 0 ? (
                <table className="table"><tbody>
                  {collectors.data.map((c) => (
                    <tr key={c.collector_id ?? "office"}>
                      <td><strong>{c.code}</strong><div className="small muted">{c.name}</div></td>
                      <td className="right">{c.count} payment(s)</td>
                      <td className="right"><strong>{money(c.total)}</strong></td>
                    </tr>
                  ))}
                </tbody></table>
              ) : null}
            </Card>
          </div>
        </>
      )}

      {can("report.export") ? (
        <Card title="Download files (CSV, opens in Excel)">
          {exportError ? <Notice kind="error">{exportError}</Notice> : null}
          <div className="table-wrap">
            <table className="table"><tbody>
              {EXPORTS.map((e) => (
                <tr key={e.name}>
                  <td><strong>{e.label}</strong><div className="small muted">{e.hint}</div></td>
                  <td className="right">
                    <button className="btn secondary" disabled={busy !== null || (e.ranged && !!problem)} onClick={() => void download(e.name)}>
                      {busy === e.name ? "Preparing…" : "Download"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody></table>
          </div>
          <p className="small muted">These files contain customer details. Keep them private. Every download is recorded in the audit log.</p>
        </Card>
      ) : null}
    </>
  );
}
