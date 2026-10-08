/** Logic behind the administration screens (users, customers, connections, audit), free of React. */

import { validAmount } from "./billingview";
import type { AuditEntry, Customer } from "./types";

// ------------------------------------------------------------------ users

export function usernameProblem(u: string): string | null {
  const t = u.trim();
  if (t.length < 3) return "The username needs at least 3 characters.";
  if (t.length > 64) return "The username is too long.";
  if (!/^[A-Za-z0-9._-]+$/.test(t)) return "Use only letters, digits, dot, dash and underscore.";
  return null;
}

export function passwordProblem(pw: string, username = ""): string | null {
  if (pw.length < 10) return "The password needs at least 10 characters.";
  if (pw.length > 128) return "The password is too long.";
  const u = username.trim().toLowerCase();
  if (u && pw.toLowerCase().includes(u)) return "The password must not contain the username.";
  if (/^(.)\1+$/.test(pw)) return "Choose a password that is not one repeated character.";
  return null;
}

// ------------------------------------------------------------------ customers

export interface CustomerForm {
  full_name: string;
  full_name_ur: string;
  father_name: string;
  cnic: string;
  mobile: string;
  whatsapp: string;
  alt_contact: string;
  area_id: string;
  house_no: string;
  address: string;
  address_ur: string;
  notes: string;
}

export const EMPTY_CUSTOMER: CustomerForm = {
  full_name: "", full_name_ur: "", father_name: "", cnic: "", mobile: "", whatsapp: "", alt_contact: "",
  area_id: "", house_no: "", address: "", address_ur: "", notes: "",
};

export function formFromCustomer(c: Customer): CustomerForm {
  return {
    full_name: c.full_name, full_name_ur: c.full_name_ur ?? "", father_name: c.father_name ?? "",
    cnic: "", // the full number is never loaded into the form; type a new one only to change it
    mobile: c.mobile ?? "", whatsapp: c.whatsapp ?? "", alt_contact: c.alt_contact ?? "",
    area_id: c.area_id ?? "", house_no: c.house_no ?? "", address: c.address ?? "",
    address_ur: c.address_ur ?? "", notes: c.notes ?? "",
  };
}

export function phoneDigits(s: string): string {
  return s.replace(/\D/g, "");
}

/** Light check: a Pakistani mobile is 11 digits (03xx...) or 12 with the 92 prefix. Blank is allowed. */
export function phoneProblem(s: string, label = "Mobile"): string | null {
  if (!s.trim()) return null;
  const d = phoneDigits(s);
  if (d.length < 10 || d.length > 13) return `${label} number looks wrong. Expected something like 0300 1234567.`;
  return null;
}

export function cnicProblem(s: string): string | null {
  if (!s.trim()) return null;
  return phoneDigits(s).length === 13 ? null : "The CNIC must have 13 digits, for example 35202-1234567-1.";
}

export function customerProblems(f: CustomerForm): string[] {
  const out: string[] = [];
  if (!f.full_name.trim()) out.push("Enter the customer's name.");
  const checks = [phoneProblem(f.mobile, "Mobile"), phoneProblem(f.whatsapp, "WhatsApp"), cnicProblem(f.cnic)];
  for (const c of checks) if (c) out.push(c);
  return out;
}

const NULLABLE: (keyof CustomerForm)[] = [
  "full_name_ur", "father_name", "mobile", "whatsapp", "alt_contact", "area_id", "house_no", "address", "address_ur", "notes",
];

/**
 * The request body for creating or editing a customer.
 * Create: every filled field. Edit: ONLY what changed, so saving never wipes something the form
 * cannot show (the stored CNIC), and clearing a field on purpose sends null.
 */
export function customerBody(form: CustomerForm, original?: CustomerForm): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  const clean = (v: string) => v.trim();
  if (!original || clean(form.full_name) !== clean(original.full_name)) body.full_name = clean(form.full_name);
  for (const k of NULLABLE) {
    const now = clean(form[k]);
    if (original) {
      if (now !== clean(original[k])) body[k] = now === "" ? null : now;
    } else if (now !== "") {
      body[k] = now;
    }
  }
  if (clean(form.cnic) !== "") body.cnic = clean(form.cnic);
  return body;
}

// ------------------------------------------------------------------ connections

export interface ServiceLineForm {
  enabled: boolean;
  package_id: string;
  price: string;
}

export interface ConnectionForm {
  connection_type: "INTERNET" | "CABLE" | "COMBINED";
  internet_id: string;
  next_due_date: string;
  internet: ServiceLineForm;
  cable: ServiceLineForm;
}

export function emptyConnection(): ConnectionForm {
  return {
    connection_type: "INTERNET", internet_id: "", next_due_date: "",
    internet: { enabled: true, package_id: "", price: "" },
    cable: { enabled: false, package_id: "", price: "" },
  };
}

/** Keeps the service lines consistent with the chosen connection type. */
export function withType(f: ConnectionForm, type: ConnectionForm["connection_type"]): ConnectionForm {
  return {
    ...f, connection_type: type,
    internet: { ...f.internet, enabled: type !== "CABLE" },
    cable: { ...f.cable, enabled: type !== "INTERNET" },
  };
}

export function connectionProblems(f: ConnectionForm): string[] {
  const out: string[] = [];
  const lines = [["internet", f.internet], ["cable", f.cable]] as const;
  for (const [name, l] of lines) {
    if (!l.enabled) continue;
    if (!l.package_id && !l.price.trim()) out.push(`Choose a ${name} package or type a ${name} price.`);
    if (l.price.trim() && !validAmount(l.price)) out.push(`The ${name} price must be an amount like 1500 or 1500.50.`);
  }
  if (f.next_due_date && !/^\d{4}-\d{2}-\d{2}$/.test(f.next_due_date)) out.push("Enter the next due date as year-month-day.");
  return out;
}

/** A connection with no due date is never billed: say so before saving. */
export function connectionWarning(f: ConnectionForm): string | null {
  return f.next_due_date ? null : "Without a next due date this connection will not be billed until you set one.";
}

export function connectionBody(f: ConnectionForm): Record<string, unknown> {
  const line = (service: string, l: ServiceLineForm) => ({
    service, package_id: l.package_id || null, price: l.price.trim() || null,
  });
  const lines = [];
  if (f.internet.enabled) lines.push(line("INTERNET", f.internet));
  if (f.cable.enabled) lines.push(line("CABLE", f.cable));
  const body: Record<string, unknown> = { connection_type: f.connection_type, service_lines: lines };
  if (f.internet_id.trim()) body.internet_id = f.internet_id.trim();
  if (f.next_due_date) body.next_due_date = f.next_due_date;
  return body;
}

// ------------------------------------------------------------------ connection status

export type TargetStatus = "ACTIVE" | "SUSPENDED" | "DISCONNECTED" | "FREE" | "TRIAL";

/** Which status changes make sense from the current one (the server still has the last word). */
export function statusChoices(current: string): { status: TargetStatus; label: string }[] {
  const all: { status: TargetStatus; label: string }[] = [
    { status: "ACTIVE", label: current === "SUSPENDED" || current === "DISCONNECTED" ? "Reactivate" : "Make active" },
    { status: "SUSPENDED", label: "Suspend (temporarily)" },
    { status: "DISCONNECTED", label: "Disconnect" },
    { status: "FREE", label: "Mark as free" },
    { status: "TRIAL", label: "Mark as trial" },
  ];
  return all.filter((o) => o.status !== current);
}

export function statusChangeProblem(args: {
  current: string; target: string; reason: string; fee: string; nextDue: string;
}): string | null {
  const { current, target, reason, fee, nextDue } = args;
  if (reason.trim().length < 3) return "Please say why (at least 3 characters).";
  const reconnecting = target === "ACTIVE" && (current === "SUSPENDED" || current === "DISCONNECTED");
  if (fee.trim() !== "") {
    if (!reconnecting) return "A reconnection fee only applies when reactivating a suspended or disconnected connection.";
    if (!validAmount(fee)) return "The reconnection fee must be an amount like 500 or 500.50.";
  }
  const billable = ["ACTIVE", "FREE", "TRIAL"].includes(target);
  if (nextDue && !billable) return "A next due date only applies when the connection will be billed.";
  if (nextDue && !/^\d{4}-\d{2}-\d{2}$/.test(nextDue)) return "Enter the next due date as year-month-day.";
  return null;
}

export function statusChangeBody(args: { target: string; reason: string; fee: string; nextDue: string }): Record<string, unknown> {
  const b: Record<string, unknown> = { status: args.target, reason: args.reason.trim() };
  if (args.fee.trim()) b.reconnection_fee = args.fee.trim();
  if (args.nextDue) b.next_due_date = args.nextDue;
  return b;
}

// ------------------------------------------------------------------ assignments

export function toggleId(list: readonly string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

export function sameSet(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && new Set(a).size === new Set(b).size && a.every((x) => b.includes(x));
}

// ------------------------------------------------------------------ audit log

const ACTION_TEXT: Record<string, string> = {
  "auth.login": "Logged in",
  "auth.logout": "Logged out",
  "user.create": "Created a user",
  "user.update": "Changed a user",
  "user.password": "Reset a password",
  "customer.create": "Created a customer",
  "customer.update": "Edited a customer",
  "customer.archive": "Archived a customer",
  "connection.create": "Added a connection",
  "connection.update": "Edited a connection",
  "connection.status": "Changed a connection's status",
  "payment.create": "Recorded a payment",
  "payment.void": "Cancelled a payment",
  "billing.run": "Ran monthly billing",
  "billing.late_fees": "Charged late fees",
  "opening_balances.load": "Loaded opening balances",
  "collector.create": "Added a collector",
  "collector.update": "Changed a collector",
  "collector.set_areas": "Set a collector's areas",
  "collector.set_customers": "Set a collector's customers",
  "import.upload": "Uploaded a customer file",
  "import.commit": "Imported customers",
};

export function describeAction(action: string): string {
  return ACTION_TEXT[action] ?? action;
}

/** The few fields worth showing at a glance, without dumping everything. */
export function auditHighlights(e: Pick<AuditEntry, "after" | "before">): string[] {
  const a = e.after ?? {};
  const out: string[] = [];
  const text = (k: string) => (typeof a[k] === "string" || typeof a[k] === "number" ? String(a[k]) : null);
  for (const [k, label] of [["amount", "amount"], ["receipt_number", "receipt"], ["reason", "reason"],
    ["status", "status"], ["invoices_created", "invoices"], ["total_billed", "total"]] as const) {
    const v = text(k);
    if (v) out.push(`${label}: ${v}`);
  }
  const b = e.before?.["status"];
  if (typeof b === "string" && out.some((x) => x.startsWith("status:"))) out.push(`was: ${b}`);
  return out.slice(0, 5);
}

/** Never show secrets that an audit entry might carry. */
export function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) =>
      [k, /pass|token|secret|cnic/i.test(k) ? "••••" : redact(v)]));
  }
  return value;
}
