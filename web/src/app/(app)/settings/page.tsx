"use client";

import { useState } from "react";

import { Card, ErrorBox, Loading, Notice, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import { FIELDS, GROUPS, changesFrom, defaultText, fieldProblem, toForm, type FieldSpec } from "@/lib/settingsview";
import type { SettingsState } from "@/lib/types";

export default function SettingsPage() {
  const state = useFetch<SettingsState>("/settings");
  if (state.loading && !state.data) return <Loading />;
  if (!state.data) return <ErrorBox message={state.error ?? "Could not load the settings."} onRetry={state.reload} />;
  // key: start the form again whenever the saved settings change
  return <SettingsForm key={JSON.stringify(state.data.values)} state={state.data} reload={state.reload} />;
}

function SettingsForm({ state, reload }: { state: SettingsState; reload: () => void }) {
  const [form, setForm] = useState<Record<string, string>>(toForm(state.values));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const changes = changesFrom(form, state.values);
  const problems = Object.keys(changes).map((k) => fieldProblem(FIELDS.find((f) => f.key === k)!, form[k])).filter((p): p is string => !!p);

  async function send(values: Record<string, string | null>) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await api("/settings", { method: "PUT", json: { values } });
      setSaved(true);
      reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the settings.");
    } finally {
      setBusy(false);
    }
  }

  function field(f: FieldSpec) {
    const overridden = state.overridden.includes(f.key);
    const set = (e: { target: { value: string } }) => setForm({ ...form, [f.key]: e.target.value });
    return (
      <div key={f.key} style={{ marginBottom: "1rem" }}>
        <label htmlFor={`s-${f.key}`}><strong>{f.label}</strong></label><br />
        {f.kind === "choice" ? (
          <select id={`s-${f.key}`} value={form[f.key]} onChange={set}>
            {f.choices?.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        ) : (
          <input id={`s-${f.key}`} type="text" value={form[f.key]} onChange={set}
            inputMode={f.kind === "text" ? undefined : "decimal"} style={{ width: f.kind === "text" ? 360 : 160, maxWidth: "100%" }} />
        )}
        {f.help ? <div className="small muted">{f.help}</div> : null}
        <div className="small muted">
          Standard: {defaultText(f, state.defaults[f.key])}
          {overridden ? (
            <> · <strong>changed</strong> · <button className="btn secondary small" disabled={busy} onClick={() => void send({ [f.key]: null })}>Use the standard</button></>
          ) : " · using the standard"}
        </div>
      </div>
    );
  }

  return (
    <>
      <PageHeader title="Settings" subtitle="Billing timing, late fees and the business details printed on receipts." />
      <Notice kind="info">
        The &ldquo;standard&rdquo; values come from the server&apos;s configuration file. Anything you change here takes
        effect immediately and is recorded in the audit log.
      </Notice>
      {saved ? <Notice kind="ok">Saved.</Notice> : null}
      {GROUPS.map((g) => (
        <Card key={g} title={g}>{FIELDS.filter((f) => f.group === g).map(field)}</Card>
      ))}
      {problems.length > 0 ? <Notice kind="warn">{problems.join(" ")}</Notice> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="actions">
        <button className="btn" disabled={busy || problems.length > 0 || Object.keys(changes).length === 0} onClick={() => void send(changes)}>
          {busy ? "Saving…" : "Save changes"}
        </button>
        {Object.keys(changes).length === 0 ? <span className="small muted">Nothing changed yet.</span> : null}
      </div>
    </>
  );
}
