"use client";

import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import { areaBody, areaProblem, type AreaForm } from "@/lib/setup";
import type { Area } from "@/lib/types";

export default function AreasPage() {
  const can = useCan();
  const list = useFetch<Area[]>("/areas");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Area | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function remove(a: Area) {
    if (!window.confirm(`Delete the area "${a.name}"?\n\nThis only works if no customer or collector uses it.`)) return;
    try {
      await api(`/areas/${a.id}`, { method: "DELETE" });
      setMsg({ kind: "ok", text: `Deleted ${a.name}.` });
      list.reload();
    } catch (e) {
      setMsg({ kind: "error", text: e instanceof ApiError ? e.message : "Could not delete." });
    }
  }

  return (
    <>
      <PageHeader title="Areas" subtitle="Neighbourhoods you serve. Customers and collectors are organised by area."
        actions={can("area.manage") ? <button className="btn" onClick={() => { setAdding(true); setEditing(null); setMsg(null); }}>Add area</button> : undefined} />
      {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
      {adding ? <AreaEditor area={null} onDone={(t) => { setAdding(false); setMsg({ kind: "ok", text: t }); list.reload(); }} onCancel={() => setAdding(false)} /> : null}
      {editing ? <AreaEditor key={editing.id} area={editing} onDone={(t) => { setEditing(null); setMsg({ kind: "ok", text: t }); list.reload(); }} onCancel={() => setEditing(null)} /> : null}
      <Card>
        {list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> : null}
        {list.loading && !list.data ? <Loading /> : null}
        {list.data && list.data.length === 0 ? <p className="muted">No areas yet.</p> : null}
        {list.data && list.data.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Name</th><th>Urdu</th><th>Code</th><th></th></tr></thead>
              <tbody>
                {list.data.map((a) => (
                  <tr key={a.id}>
                    <td><strong>{a.name}</strong></td>
                    <td className="urdu">{a.name_ur}</td>
                    <td>{a.code}</td>
                    <td>{can("area.manage") ? (
                      <div className="actions">
                        <button className="btn secondary small" onClick={() => { setEditing(a); setAdding(false); setMsg(null); }}>Edit</button>
                        <button className="btn secondary small" onClick={() => void remove(a)}>Delete</button>
                      </div>
                    ) : null}</td>
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

function AreaEditor({ area, onDone, onCancel }: { area: Area | null; onDone: (msg: string) => void; onCancel: () => void }) {
  const original: AreaForm | undefined = area ? { name: area.name, name_ur: area.name_ur ?? "", code: area.code ?? "" } : undefined;
  const [form, setForm] = useState<AreaForm>(original ?? { name: "", name_ur: "", code: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const problem = areaProblem(form);
  const body = areaBody(form, original);
  const changed = Object.keys(body).length > 0;

  async function save() {
    if (problem || !changed || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (area) await api(`/areas/${area.id}`, { method: "PATCH", json: body });
      else await api("/areas", { json: body });
      onDone(area ? `Saved ${form.name}.` : `Added ${form.name}.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save.");
      setBusy(false);
    }
  }

  return (
    <Card title={area ? `Edit ${area.name}` : "Add an area"}>
      <div className="toolbar">
        <input type="text" placeholder="Name" aria-label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input type="text" className="urdu" placeholder="نام (Urdu)" aria-label="Name in Urdu" value={form.name_ur} onChange={(e) => setForm({ ...form, name_ur: e.target.value })} />
        <input type="text" placeholder="Code (optional)" aria-label="Code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} style={{ width: 150 }} />
        <button className="btn" disabled={busy || !!problem || !changed} onClick={() => void save()}>{busy ? "Saving…" : "Save"}</button>
        <button className="btn secondary" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </Card>
  );
}
