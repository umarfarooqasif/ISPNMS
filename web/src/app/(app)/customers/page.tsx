"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Card, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { qs } from "@/lib/api";
import { useDebounced, useFetch } from "@/lib/hooks";
import type { Area, Customer } from "@/lib/types";

const PAGE = 25;
const STATUSES = [
  { value: "ACTIVE", label: "Active" },
  { value: "INACTIVE", label: "Inactive" },
  { value: "ARCHIVED", label: "Archived" },
  { value: "", label: "All (not archived)" },
];

export default function CustomersPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("ACTIVE");
  const dq = useDebounced(q, 300).trim();

  // The page number belongs to one search; a new search starts again at page 1.
  const key = `${dq}|${status}`;
  const [pageState, setPageState] = useState({ key, page: 0 });
  const page = pageState.key === key ? pageState.page : 0;

  const list = useFetch<Customer[]>(`/customers${qs({ q: dq, status, limit: PAGE + 1, offset: page * PAGE })}`);
  const areas = useFetch<Area[]>("/areas");
  const areaName = useMemo(() => new Map((areas.data ?? []).map((a) => [a.id, a.name])), [areas.data]);

  const rows = (list.data ?? []).slice(0, PAGE);
  const hasNext = (list.data?.length ?? 0) > PAGE;

  return (
    <>
      <PageHeader title="Customers" subtitle="Search by name, customer ID, mobile, house number or Internet ID." />
      <Card>
        <div className="toolbar">
          <input type="search" placeholder="Search customers…" value={q} aria-label="Search customers"
            onChange={(e) => setQ(e.target.value)} />
          <select value={status} aria-label="Status" onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>

        {list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> : null}
        {list.loading && !list.data ? <Loading /> : null}
        {list.data && rows.length === 0 ? <p className="muted">No customers found.</p> : null}

        {rows.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>ID</th><th>Name</th><th>Mobile</th><th>Area</th><th>House</th><th>Status</th></tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id}>
                    <td className="mono">{c.customer_code}</td>
                    <td>
                      <Link href={`/customers/${c.id}`}>{c.full_name}</Link>
                      {c.full_name_ur ? <div className="urdu small muted">{c.full_name_ur}</div> : null}
                    </td>
                    <td>{c.mobile ?? <span className="muted">none</span>}</td>
                    <td>{(c.area_id && areaName.get(c.area_id)) || ""}</td>
                    <td>{c.house_no ?? ""}</td>
                    <td><StatusBadge status={c.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="pager">
          <button className="btn secondary small" disabled={page === 0}
            onClick={() => setPageState({ key, page: page - 1 })}>← Previous</button>
          <span className="muted small">Page {page + 1}</span>
          <button className="btn secondary small" disabled={!hasNext}
            onClick={() => setPageState({ key, page: page + 1 })}>Next →</button>
        </div>
      </Card>
    </>
  );
}
