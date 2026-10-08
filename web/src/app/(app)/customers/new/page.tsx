"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { CustomerFormFields } from "@/components/CustomerFormFields";
import { useCan } from "@/components/Shell";
import { Card, Notice, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { EMPTY_CUSTOMER, customerBody, customerProblems } from "@/lib/adminview";
import { useFetch } from "@/lib/hooks";
import type { Area, Customer } from "@/lib/types";

export default function NewCustomerPage() {
  const router = useRouter();
  const can = useCan();
  const areas = useFetch<Area[]>("/areas");
  const [form, setForm] = useState(EMPTY_CUSTOMER);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const problems = customerProblems(form);

  async function save() {
    if (problems.length || busy) return;
    setBusy(true);
    setError(null);
    try {
      const c = await api<Customer>("/customers", { json: customerBody(form) });
      router.push(`/customers/${c.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the customer.");
      setBusy(false);
    }
  }

  if (!can("customer.create")) return <Notice kind="warn">You do not have permission to add customers.</Notice>;
  return (
    <>
      <p className="small"><Link href="/customers">← All customers</Link></p>
      <PageHeader title="New customer" subtitle="Only the name is required. You can add the connection on the next page." />
      <Card>
        <CustomerFormFields form={form} onChange={setForm} areas={areas.data ?? []} />
        {form.mobile.trim() === "" ? <Notice kind="info">Without a mobile number the customer cannot be matched to a Wasooli row later.</Notice> : null}
        {problems.length > 0 && form.full_name.trim() !== "" ? <Notice kind="warn">{problems.join(" ")}</Notice> : null}
        {error ? <Notice kind="error">{error}</Notice> : null}
        <div className="actions" style={{ marginTop: ".75rem" }}>
          <button className="btn" disabled={busy || problems.length > 0} onClick={() => void save()}>{busy ? "Saving…" : "Save customer"}</button>
          <Link className="btn secondary" href="/customers">Cancel</Link>
        </div>
      </Card>
    </>
  );
}
