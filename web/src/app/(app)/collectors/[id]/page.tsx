"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Card, ErrorBox, Loading, Notice, PageHeader } from "@/components/ui";
import { api, ApiError, qs } from "@/lib/api";
import { sameSet, toggleId } from "@/lib/adminview";
import { useDebounced, useFetch } from "@/lib/hooks";
import type { Area, AssignedCustomer, Assignments, CollectorRow, Customer } from "@/lib/types";

export default function CollectorPage() {
  const { id } = useParams<{ id: string }>();
  const collectors = useFetch<CollectorRow[]>("/collectors");
  const assignments = useFetch<Assignments>(`/collectors/${id}/assignments`);
  const areas = useFetch<Area[]>("/areas");
  const collector = collectors.data?.find((c) => c.id === id);

  if (assignments.loading && !assignments.data) return <Loading />;
  if (!assignments.data) return <ErrorBox message={assignments.error ?? "Collector not found."} onRetry={assignments.reload} />;

  return (
    <>
      <p className="small"><Link href="/collectors">← All collectors</Link></p>
      <PageHeader title={collector ? `${collector.code} · ${collector.full_name ?? collector.username ?? ""}` : "Collector"}
        subtitle="What this collector sees on their phone. Changes reach the phone the next time it syncs." />
      {/* key: reset the editors when the saved data is reloaded */}
      <AreasEditor key={`a-${assignments.data.area_ids.join(",")}`} id={id} areas={areas.data ?? []} saved={assignments.data.area_ids} onSaved={assignments.reload} />
      <CustomersEditor key={`c-${assignments.data.customers.map((c) => c.customer_id).join(",")}`} id={id} saved={assignments.data.customers} onSaved={assignments.reload} />
    </>
  );
}

function AreasEditor({ id, areas, saved, onSaved }: { id: string; areas: Area[]; saved: string[]; onSaved: () => void }) {
  const [picked, setPicked] = useState<string[]>(saved);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const dirty = !sameSet(picked, saved);

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      await api(`/collectors/${id}/areas`, { method: "PUT", json: { area_ids: picked } });
      setMsg({ kind: "ok", text: "Areas saved." });
      onSaved();
    } catch (e) {
      setMsg({ kind: "error", text: e instanceof ApiError ? e.message : "Could not save." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Whole areas" actions={<button className="btn" disabled={!dirty || busy} onClick={() => void save()}>{busy ? "Saving…" : "Save areas"}</button>}>
      <p className="small muted">Every customer in a ticked area appears on this collector&apos;s phone, including customers added later.</p>
      {areas.length === 0 ? <p className="muted">No areas yet.</p> : (
        <div className="chips">
          {areas.map((a) => (
            <label key={a.id} className={`chip ${picked.includes(a.id) ? "active" : ""}`}>
              <input type="checkbox" checked={picked.includes(a.id)} onChange={() => setPicked(toggleId(picked, a.id))} style={{ display: "none" }} />
              {a.name}
            </label>
          ))}
        </div>
      )}
      {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
    </Card>
  );
}

function CustomersEditor({ id, saved, onSaved }: { id: string; saved: AssignedCustomer[]; onSaved: () => void }) {
  const [list, setList] = useState<AssignedCustomer[]>(saved);
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 300).trim();
  const found = useFetch<Customer[]>(dq.length >= 2 ? `/customers${qs({ q: dq, limit: 8 })}` : null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const dirty = !sameSet(list.map((c) => c.customer_id), saved.map((c) => c.customer_id)) ||
    list.some((c, i) => c.customer_id !== saved[i]?.customer_id);

  const has = (cid: string) => list.some((c) => c.customer_id === cid);
  const add = (c: Customer) => setList([...list, { customer_id: c.id, customer_code: c.customer_code, full_name: c.full_name, sort_order: list.length }]);
  const remove = (cid: string) => setList(list.filter((c) => c.customer_id !== cid));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= list.length) return;
    const next = [...list];
    [next[i], next[j]] = [next[j], next[i]];
    setList(next);
  };

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      await api(`/collectors/${id}/customers`, { method: "PUT", json: { customers: list.map((c, i) => ({ customer_id: c.customer_id, sort_order: i })) } });
      setMsg({ kind: "ok", text: "Customers saved." });
      onSaved();
    } catch (e) {
      setMsg({ kind: "error", text: e instanceof ApiError ? e.message : "Could not save." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={`Individual customers (${list.length})`} actions={<button className="btn" disabled={!dirty || busy} onClick={() => void save()}>{busy ? "Saving…" : "Save customers"}</button>}>
      <p className="small muted">Use this for customers outside the ticked areas, or to set a visiting order.</p>
      <div className="toolbar">
        <input type="search" placeholder="Find a customer to add…" aria-label="Find a customer" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {found.data && found.data.length > 0 ? (
        <div className="chips" style={{ marginBottom: ".75rem" }}>
          {found.data.map((c) => (
            <button key={c.id} className="chip" disabled={has(c.id)} onClick={() => add(c)}>
              {has(c.id) ? "✓ " : "+ "}{c.full_name} <span className="muted">{c.customer_code}</span>
            </button>
          ))}
        </div>
      ) : null}
      {dq.length >= 2 && found.data && found.data.length === 0 ? <p className="small muted">No customer matches.</p> : null}

      {list.length === 0 ? <p className="muted">No individually assigned customers.</p> : (
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {list.map((c, i) => (
                <tr key={c.customer_id}>
                  <td className="muted" style={{ width: 40 }}>{i + 1}</td>
                  <td><Link href={`/customers/${c.customer_id}`}>{c.full_name}</Link> <span className="small muted">{c.customer_code}</span></td>
                  <td className="right">
                    <div className="actions" style={{ justifyContent: "flex-end" }}>
                      <button className="btn secondary small" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                      <button className="btn secondary small" aria-label="Move down" disabled={i === list.length - 1} onClick={() => move(i, 1)}>↓</button>
                      <button className="btn secondary small" onClick={() => remove(c.customer_id)}>Remove</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
    </Card>
  );
}
