"use client";

import { useState, type FormEvent } from "react";

import { CSRF_HEADER, CSRF_VALUE } from "@/lib/bff-core";
import { detailOf } from "@/lib/api";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json", [CSRF_HEADER]: CSRF_VALUE },
        body: JSON.stringify({ username, password }),
      });
      if (res.ok) {
        window.location.href = "/"; // full load so the new cookies are used straight away
        return;
      }
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        body = null;
      }
      setError(detailOf(body, "Could not log in. Please try again."));
    } catch {
      setError("Could not reach the server. Check your internet connection.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <h1>ISP Billing</h1>
        <p className="muted">Log in to continue</p>
        <label htmlFor="u">Username</label>
        <input id="u" type="text" autoComplete="username" autoFocus required value={username}
          onChange={(e) => setUsername(e.target.value)} />
        <label htmlFor="p">Password</label>
        <input id="p" type="password" autoComplete="current-password" required value={password}
          onChange={(e) => setPassword(e.target.value)} />
        {error ? <div className="notice error" role="alert" style={{ marginTop: "1rem" }}>{error}</div> : null}
        <button className="btn" type="submit" disabled={busy}>{busy ? "Logging in…" : "Log in"}</button>
      </form>
    </div>
  );
}
