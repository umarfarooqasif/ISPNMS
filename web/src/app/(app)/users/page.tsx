"use client";

import { useState } from "react";

import { useCan, useMe } from "@/components/Shell";
import { Badge, Card, ErrorBox, Loading, Notice, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { passwordProblem, toggleId, usernameProblem } from "@/lib/adminview";
import { useFetch } from "@/lib/hooks";
import type { RoleRow, UserRow } from "@/lib/types";

export default function UsersPage() {
  const can = useCan();
  const me = useMe();
  const users = useFetch<UserRow[]>("/users");
  const roles = useFetch<RoleRow[]>("/roles");
  // Only a super admin may hand out the super_admin role (the server enforces it too).
  const grantable = (roles.data ?? []).filter((r) => r.code !== "super_admin" || can("role.manage"));
  const roleName = (code: string) => roles.data?.find((r) => r.code === code)?.name ?? code;

  const [editing, setEditing] = useState<UserRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  return (
    <>
      <PageHeader title="Users" subtitle="Who can log in, and what they may do."
        actions={<button className="btn" onClick={() => { setCreating(!creating); setEditing(null); }}>Add user</button>} />
      {notice ? <Notice kind="ok">{notice}</Notice> : null}
      {creating ? (
        <CreateUser roles={grantable} onDone={(msg) => { setCreating(false); setNotice(msg); users.reload(); }} onCancel={() => setCreating(false)} />
      ) : null}
      {editing ? (
        <EditUser key={editing.id} user={editing} roles={grantable} isSelf={editing.id === me.id}
          onDone={(msg) => { setEditing(null); setNotice(msg); users.reload(); }} onCancel={() => setEditing(null)} />
      ) : null}

      <Card>
        {users.error ? <ErrorBox message={users.error} onRetry={users.reload} /> : null}
        {users.loading && !users.data ? <Loading /> : null}
        {users.data ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Name</th><th>Username</th><th>Roles</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {users.data.map((u) => (
                  <tr key={u.id}>
                    <td><strong>{u.full_name}</strong>{u.email ? <div className="small muted">{u.email}</div> : null}</td>
                    <td className="mono">{u.username}</td>
                    <td><div className="chips">{u.role_codes.map((r) => <Badge key={r} tone="blue">{roleName(r)}</Badge>)}</div></td>
                    <td>{u.is_active ? <Badge tone="green">active</Badge> : <Badge tone="red">disabled</Badge>}</td>
                    <td><button className="btn secondary small" onClick={() => { setEditing(u); setCreating(false); setNotice(null); }}>Edit</button></td>
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

function RolePicker({ roles, value, onChange }: { roles: RoleRow[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div>
      <div className="small muted">Roles</div>
      {roles.map((r) => (
        <label key={r.code} style={{ display: "block" }} title={r.permissions.join(", ")}>
          <input type="checkbox" checked={value.includes(r.code)} onChange={() => onChange(toggleId(value, r.code))} /> {r.name}
        </label>
      ))}
    </div>
  );
}

function CreateUser({ roles, onDone, onCancel }: { roles: RoleRow[]; onDone: (msg: string) => void; onCancel: () => void }) {
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const problem = usernameProblem(username) ?? (fullName.trim() ? null : "Enter the person's name.") ?? passwordProblem(password, username);
  const problemShown = username || fullName || password ? problem : null; // stay quiet until they start typing

  async function save() {
    if (problem || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api("/users", { json: { username: username.trim(), full_name: fullName.trim(), email: email.trim() || null, password, role_codes: picked } });
      onDone(`User ${username.trim()} created. Give them the password in person; they can log in now.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create the user.");
      setBusy(false);
    }
  }

  return (
    <Card title="Add a user">
      <div className="grid">
        <div><label className="small muted" htmlFor="nu">Username</label><br /><input id="nu" type="text" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} style={{ width: "100%" }} /></div>
        <div><label className="small muted" htmlFor="nf">Full name</label><br /><input id="nf" type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} style={{ width: "100%" }} /></div>
        <div><label className="small muted" htmlFor="ne">Email (optional)</label><br /><input id="ne" type="text" value={email} onChange={(e) => setEmail(e.target.value)} style={{ width: "100%" }} /></div>
        <div><label className="small muted" htmlFor="np">Password (10+ characters)</label><br /><input id="np" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} style={{ width: "100%" }} /></div>
        <RolePicker roles={roles} value={picked} onChange={setPicked} />
      </div>
      {problemShown ? <Notice kind="warn">{problemShown}</Notice> : null}
      {picked.length === 0 ? <p className="small muted">With no role selected the user can log in but cannot do anything.</p> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="actions">
        <button className="btn" disabled={busy || !!problem} onClick={() => void save()}>{busy ? "Saving…" : "Create user"}</button>
        <button className="btn secondary" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </Card>
  );
}

function EditUser({ user, roles, isSelf, onDone, onCancel }: {
  user: UserRow; roles: RoleRow[]; isSelf: boolean; onDone: (msg: string) => void; onCancel: () => void;
}) {
  const [fullName, setFullName] = useState(user.full_name);
  const [email, setEmail] = useState(user.email ?? "");
  const [active, setActive] = useState(user.is_active);
  const [picked, setPicked] = useState<string[]>(user.role_codes);
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>, done: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try { await fn(); onDone(done); } catch (e) { setError(e instanceof ApiError ? e.message : "Something went wrong."); setBusy(false); }
  }

  const pwProblem = pw ? passwordProblem(pw, user.username) : null;

  return (
    <Card title={`Edit ${user.username}`}>
      <div className="grid">
        <div><label className="small muted" htmlFor="ef">Full name</label><br /><input id="ef" type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} style={{ width: "100%" }} /></div>
        <div><label className="small muted" htmlFor="ee">Email</label><br /><input id="ee" type="text" value={email} onChange={(e) => setEmail(e.target.value)} style={{ width: "100%" }} /></div>
        <div>
          <label><input type="checkbox" checked={active} disabled={isSelf} onChange={(e) => setActive(e.target.checked)} /> Can log in</label>
          {isSelf ? <div className="small muted">You cannot disable your own account.</div> : null}
        </div>
        <RolePicker roles={roles} value={picked} onChange={setPicked} />
      </div>
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="actions">
        <button className="btn" disabled={busy || !fullName.trim()}
          onClick={() => void run(() => api(`/users/${user.id}`, { method: "PATCH", json: { full_name: fullName.trim(), email: email.trim() || null, is_active: active, role_codes: picked } }), `Saved ${user.username}.`)}>
          Save changes
        </button>
        <button className="btn secondary" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
      <hr style={{ border: 0, borderTop: "1px solid var(--line)", margin: "1rem 0" }} />
      <div className="toolbar">
        <input type="password" autoComplete="new-password" placeholder="New password" aria-label="New password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <button className="btn secondary" disabled={busy || !pw || !!pwProblem}
          onClick={() => { if (window.confirm(`Reset the password for ${user.username}?`)) void run(() => api(`/users/${user.id}/password`, { json: { password: pw } }), `Password for ${user.username} was reset.`); }}>
          Reset password
        </button>
      </div>
      {pwProblem ? <Notice kind="warn">{pwProblem}</Notice> : null}
    </Card>
  );
}
