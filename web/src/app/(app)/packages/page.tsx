"use client";

import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice, PageHeader, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { money } from "@/lib/format";
import { useFetch } from "@/lib/hooks";
import {
  EMPTY_PACKAGE, PRICE_NOTE, formFromPackage, packageBody, packageProblems, packageWarning, type PackageForm,
} from "@/lib/setup";
import type { PackageFull } from "@/lib/types";

export default function PackagesPage() {
  const can = useCan();
  const list = useFetch<PackageFull[]>("/packages");
  const [editing, setEditing] = useState<PackageFull | "new" | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  return (
    <>
      <PageHeader title="Packages" subtitle="The internet and cable plans you sell, and their standard prices."
        actions={can("package.manage") ? <button className="btn" onClick={() => { setEditing("new"); setSaved(null); }}>Add package</button> : undefined} />
      <Notice kind="info">{PRICE_NOTE}</Notice>
      {saved ? <Notice kind="ok">{saved}</Notice> : null}
      {editing ? (
        <PackageEditor key={editing === "new" ? "new" : editing.id} pkg={editing === "new" ? null : editing}
          onDone={(msg) => { setEditing(null); setSaved(msg); list.reload(); }} onCancel={() => setEditing(null)} />
      ) : null}
      <Card>
        {list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> : null}
        {list.loading && !list.data ? <Loading /> : null}
        {list.data && list.data.length === 0 ? <p className="muted">No packages yet.</p> : null}
        {list.data && list.data.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Package</th><th>Code</th><th className="right">Internet</th><th className="right">Cable</th><th className="right">Monthly</th><th>Speed</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {list.data.map((p) => (
                  <tr key={p.id}>
                    <td><strong>{p.display_name}</strong>{p.display_name_ur ? <div className="urdu small muted">{p.display_name_ur}</div> : null}</td>
                    <td className="mono">{p.code}</td>
                    <td className="right">{money(p.internet_price)}</td>
                    <td className="right">{money(p.cable_price)}</td>
                    <td className="right">{money(p.monthly_price)}</td>
                    <td>{p.speed_mbps ? `${p.speed_mbps} Mbps` : ""}</td>
                    <td><StatusBadge status={p.status} /></td>
                    <td>{can("package.manage") ? <button className="btn secondary small" onClick={() => { setEditing(p); setSaved(null); }}>Edit</button> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
    </>
  );
}

function PackageEditor({ pkg, onDone, onCancel }: { pkg: PackageFull | null; onDone: (msg: string) => void; onCancel: () => void }) {
  const original = pkg ? formFromPackage(pkg) : undefined;
  const [form, setForm] = useState<PackageForm>(original ?? EMPTY_PACKAGE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const problems = packageProblems(form, !pkg);
  const body = packageBody(form, original);
  const changed = Object.keys(body).length > 0;
  const warning = packageWarning(form);
  const set = (k: keyof PackageForm) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const input = (label: string, k: keyof PackageForm, extra: { placeholder?: string; disabled?: boolean; urdu?: boolean } = {}) => (
    <div>
      <label className="small muted" htmlFor={`pk-${k}`}>{label}</label><br />
      <input id={`pk-${k}`} type="text" value={form[k]} placeholder={extra.placeholder} disabled={extra.disabled}
        className={extra.urdu ? "urdu" : undefined} onChange={set(k)} style={{ width: "100%" }} />
    </div>
  );

  async function save() {
    if (problems.length || !changed || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (pkg) await api(`/packages/${pkg.id}`, { method: "PATCH", json: body });
      else await api("/packages", { json: body });
      onDone(pkg ? `Saved ${form.display_name}.` : `Added ${form.display_name}.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the package.");
      setBusy(false);
    }
  }

  return (
    <Card title={pkg ? `Edit ${pkg.display_name}` : "Add a package"}>
      <div className="grid">
        {input("Code (cannot be changed later)", "code", { placeholder: "star3", disabled: !!pkg })}
        {input("Name", "name")}
        {input("Name shown to customers", "display_name")}
        {input("Name in Urdu", "display_name_ur", { urdu: true })}
        {input("Internet price (Rs per month)", "internet_price", { placeholder: "1200" })}
        {input("Cable price (Rs per month)", "cable_price", { placeholder: "300" })}
        {input("Combined monthly price (Rs)", "monthly_price")}
        {input("Speed (Mbps)", "speed_mbps")}
        {input("Description", "description")}
        <div>
          <label className="small muted" htmlFor="pk-status">Status</label><br />
          <select id="pk-status" value={form.status} onChange={set("status")}>
            <option value="ACTIVE">Active (can be chosen)</option>
            <option value="INACTIVE">Inactive (hidden from new connections)</option>
          </select>
        </div>
      </div>
      {warning ? <Notice kind="info">{warning}</Notice> : null}
      {problems.length > 0 ? <Notice kind="warn">{problems.join(" ")}</Notice> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="actions" style={{ marginTop: ".75rem" }}>
        <button className="btn" disabled={busy || problems.length > 0 || !changed} onClick={() => void save()}>{busy ? "Saving…" : "Save package"}</button>
        <button className="btn secondary" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </Card>
  );
}
