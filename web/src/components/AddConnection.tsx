"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import {
  connectionBody, connectionProblems, connectionWarning, emptyConnection, withType,
  type ConnectionForm, type ServiceLineForm,
} from "@/lib/adminview";
import { money } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import type { PackageRow } from "@/lib/types";
import { Card, Notice } from "./ui";

export function AddConnection({ customerId, onSaved, onClose }: {
  customerId: string;
  onSaved: () => void;
  onClose: () => void;
}) {
  const packages = useFetch<PackageRow[]>("/packages");
  const [form, setForm] = useState<ConnectionForm>(emptyConnection());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const problems = connectionProblems(form);
  const warning = connectionWarning(form);
  const active = (packages.data ?? []).filter((p) => p.status === "ACTIVE");

  function line(name: "internet" | "cable", l: ServiceLineForm) {
    if (!l.enabled) return null;
    const list = active.filter((p) => (name === "internet" ? p.internet_price !== null || p.monthly_price !== null : p.cable_price !== null || p.monthly_price !== null));
    const set = (patch: Partial<ServiceLineForm>) => setForm({ ...form, [name]: { ...l, ...patch } });
    return (
      <div className="toolbar" key={name}>
        <strong style={{ width: 70 }}>{name === "internet" ? "Internet" : "Cable"}</strong>
        <select aria-label={`${name} package`} value={l.package_id} onChange={(e) => set({ package_id: e.target.value })}>
          <option value="">Choose a package…</option>
          {list.map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name} {money(name === "internet" ? p.internet_price ?? p.monthly_price : p.cable_price ?? p.monthly_price)}
            </option>
          ))}
        </select>
        <input type="text" inputMode="decimal" placeholder="Price (empty = package price)" aria-label={`${name} price`}
          value={l.price} onChange={(e) => set({ price: e.target.value })} style={{ width: 210 }} />
      </div>
    );
  }

  async function save() {
    if (problems.length || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/customers/${customerId}/connections`, { json: connectionBody(form) });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not add the connection.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Add a connection">
      <div className="toolbar">
        <select aria-label="Type" value={form.connection_type}
          onChange={(e) => setForm(withType(form, e.target.value as ConnectionForm["connection_type"]))}>
          <option value="INTERNET">Internet</option>
          <option value="CABLE">Cable</option>
          <option value="COMBINED">Internet + cable</option>
        </select>
        <input type="text" placeholder="Internet ID / username" aria-label="Internet ID" value={form.internet_id}
          onChange={(e) => setForm({ ...form, internet_id: e.target.value })} />
        <label className="small muted">Next due date <input type="date" value={form.next_due_date}
          onChange={(e) => setForm({ ...form, next_due_date: e.target.value })} /></label>
      </div>
      {line("internet", form.internet)}
      {line("cable", form.cable)}
      {packages.error ? <Notice kind="warn">Could not load packages: {packages.error}. You can still type prices.</Notice> : null}
      {warning ? <Notice kind="info">{warning}</Notice> : null}
      {problems.length > 0 ? <Notice kind="warn">{problems.join(" ")}</Notice> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="actions">
        <button className="btn" disabled={busy || problems.length > 0} onClick={() => void save()}>{busy ? "Saving…" : "Add connection"}</button>
        <button className="btn secondary" disabled={busy} onClick={onClose}>Cancel</button>
      </div>
    </Card>
  );
}
