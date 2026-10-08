"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { EMPTY_CUSTOMER, customerBody, customerProblems, formFromCustomer } from "@/lib/adminview";
import type { Area, Customer } from "@/lib/types";
import { CustomerFormFields } from "./CustomerFormFields";
import { Card, Notice } from "./ui";

export function EditCustomer({ customer, areas, onSaved, onClose }: {
  customer: Customer;
  areas: Area[];
  onSaved: () => void;
  onClose: () => void;
}) {
  const original = formFromCustomer(customer);
  const [form, setForm] = useState({ ...EMPTY_CUSTOMER, ...original });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const problems = customerProblems(form);
  const body = customerBody(form, original);
  const changed = Object.keys(body).length > 0;

  async function save() {
    if (problems.length || !changed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/customers/${customer.id}`, { method: "PATCH", json: body });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Edit customer">
      <CustomerFormFields form={form} onChange={setForm} areas={areas} editing />
      {problems.length > 0 ? <Notice kind="warn">{problems.join(" ")}</Notice> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="actions" style={{ marginTop: ".75rem" }}>
        <button className="btn" disabled={busy || problems.length > 0 || !changed} onClick={() => void save()}>
          {busy ? "Saving…" : "Save changes"}
        </button>
        <button className="btn secondary" disabled={busy} onClick={onClose}>Cancel</button>
        {!changed ? <span className="small muted">Nothing changed yet.</span> : null}
      </div>
    </Card>
  );
}
