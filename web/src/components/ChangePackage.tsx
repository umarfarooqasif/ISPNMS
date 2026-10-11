"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { money } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import { overrideWarning, planBody, planProblems, servicesFor, type PlanService } from "@/lib/planview";
import type { Connection, PackageRow } from "@/lib/types";
import { Notice } from "./ui";

/** Moves one service of a connection to another package or price, from the NEXT bill. */
export function ChangePackage({ connection, onChanged }: { connection: Connection; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const services = servicesFor(connection.connection_type);
  const [service, setService] = useState<PlanService>(services[0]);
  const [packageId, setPackageId] = useState("");
  const [price, setPrice] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const packages = useFetch<PackageRow[]>(open ? "/packages" : null);

  const form = { service, packageId, price, reason };
  const problems = planProblems(form);
  const warning = overrideWarning(connection.monthly_price_override);
  const active = (packages.data ?? []).filter((p) => p.status === "ACTIVE");
  const priceOf = (p: PackageRow) => (service === "INTERNET" ? p.internet_price ?? p.monthly_price : p.cable_price ?? p.monthly_price);

  async function save() {
    if (problems.length || busy) return;
    if (!window.confirm(`Change ${service.toLowerCase()} for ${connection.connection_code}?\n\nIt applies from the next bill. Bills already created are not changed.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/connections/${connection.id}/package`, { json: planBody(form) });
      setDone("Changed. The next bill will use the new price.");
      setOpen(false);
      setPackageId(""); setPrice(""); setReason("");
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not change the package.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div>
        <button className="btn secondary small" onClick={() => { setOpen(true); setDone(null); }}>Change package</button>
        {done ? <div className="small muted">{done}</div> : null}
      </div>
    );
  }
  return (
    <div style={{ minWidth: 280 }}>
      {services.length > 1 ? (
        <select aria-label="Service" value={service} onChange={(e) => setService(e.target.value as PlanService)}>
          {services.map((s) => <option key={s} value={s}>{s === "INTERNET" ? "Internet" : "Cable"}</option>)}
        </select>
      ) : null}
      <select aria-label="New package" value={packageId} onChange={(e) => setPackageId(e.target.value)} style={{ width: "100%", marginTop: ".35rem" }}>
        <option value="">Keep the package…</option>
        {active.map((p) => <option key={p.id} value={p.id}>{p.display_name} {money(priceOf(p))}</option>)}
      </select>
      <input type="text" inputMode="decimal" placeholder="Own price (empty = the package price)" aria-label="Price" value={price}
        onChange={(e) => setPrice(e.target.value)} style={{ width: "100%", marginTop: ".35rem" }} />
      <input type="text" placeholder="Reason (required)" aria-label="Reason" value={reason}
        onChange={(e) => setReason(e.target.value)} style={{ width: "100%", marginTop: ".35rem" }} />
      {warning ? <Notice kind="warn">{warning}</Notice> : null}
      {reason.trim() !== "" && problems.length > 0 ? <div className="small" style={{ color: "var(--red)" }}>{problems.join(" ")}</div> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <p className="small muted">Applies from the next bill. Bills already created are not changed.</p>
      <div className="actions">
        <button className="btn small" disabled={busy || problems.length > 0} onClick={() => void save()}>{busy ? "Saving…" : "Apply"}</button>
        <button className="btn secondary small" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}
