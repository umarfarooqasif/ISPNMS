import type { ReactNode } from "react";

import { toneFor, type Tone } from "@/lib/tones";

export function Badge({ tone, children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge ${tone ?? "gray"}`}>{children}</span>;
}

export function StatusBadge({ status, label }: { status: string | null | undefined; label?: string }) {
  if (!status) return null;
  return <Badge tone={toneFor(status)}>{label ?? status.replace(/_/g, " ").toLowerCase()}</Badge>;
}

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">
          {title ? <h2>{title}</h2> : <span />}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat">
      <div className="v">{value}</div>
      <div className="l">{label}</div>
      {hint ? <div className="l">{hint}</div> : null}
    </div>
  );
}

export function Notice({ kind, children }: { kind: "ok" | "error" | "warn" | "info"; children: ReactNode }) {
  return <div className={`notice ${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Notice kind="error">
      {message}{" "}
      {onRetry ? (
        <button className="btn secondary small" onClick={onRetry}>Try again</button>
      ) : null}
    </Notice>
  );
}

export function Loading({ text = "Loading…" }: { text?: string }) {
  return <p className="muted">{text}</p>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="card-head" style={{ marginBottom: "1rem" }}>
      <div>
        <h1>{title}</h1>
        {subtitle ? <div className="muted">{subtitle}</div> : null}
      </div>
      {actions}
    </div>
  );
}
