/** The settings form: what each setting is, how it is checked, and what changed. Pure, so it is testable. */

export type SettingKind = "int" | "money" | "choice" | "text";

export interface FieldSpec {
  key: string;
  group: string;
  label: string;
  help: string;
  kind: SettingKind;
  min?: number;
  max?: number;
  choices?: { value: string; label: string }[];
  maxLength?: number;
}

export const FIELDS: FieldSpec[] = [
  { key: "billing.lead_days", group: "Billing", label: "Bill this many days before the due date", kind: "int", min: 0, max: 60,
    help: "A bill run creates the bill for every customer whose due date is within this many days." },
  { key: "late_fee.amount", group: "Late fees", label: "Late fee per overdue bill (Rs)", kind: "money",
    help: "A flat fee charged once for each overdue bill. Enter 0 to switch late fees off." },
  { key: "late_fee.grace_days", group: "Late fees", label: "Grace days", kind: "int", min: 0, max: 90,
    help: "A bill must be this many days past its due date before a late fee can be charged." },
  { key: "late_fee.due_days", group: "Late fees", label: "Days to pay a late fee", kind: "int", min: 0, max: 90,
    help: "How long a customer has to pay the fee itself." },
  { key: "import.recharge_date_means", group: "Importing customers", label: "What the Wasooli recharge date means", kind: "choice",
    choices: [{ value: "NEXT_DUE", label: "The date the next payment is due" }, { value: "LAST_RECHARGE", label: "The date the customer last paid" }],
    help: "Applies to customers imported from now on. Customers already imported are not changed." },
  { key: "company.name", group: "Business details (printed on receipts)", label: "Business name", kind: "text", maxLength: 120, help: "" },
  { key: "company.phone", group: "Business details (printed on receipts)", label: "Phone", kind: "text", maxLength: 40, help: "" },
  { key: "company.address", group: "Business details (printed on receipts)", label: "Address", kind: "text", maxLength: 200, help: "" },
];

export const GROUPS: string[] = Array.from(new Set(FIELDS.map((f) => f.group)));

const INT = /^\d{1,4}$/;
const MONEY = /^\d{1,9}(\.\d{1,2})?$/;

/** The value as it should be compared and sent: "75" and "75.00" are the same fee. */
export function normalize(spec: FieldSpec, text: string): string {
  const t = text.trim();
  if (spec.kind === "int" && INT.test(t)) return String(Number(t));
  if (spec.kind === "money" && MONEY.test(t)) {
    const [whole, frac = ""] = t.split(".");
    return `${whole.replace(/^0+(?=\d)/, "")}.${(frac + "00").slice(0, 2)}`;
  }
  if (spec.kind === "text") return t.replace(/\s+/g, " ");
  return t;
}

/** The same checks the server makes, so mistakes are caught before saving. */
export function fieldProblem(spec: FieldSpec, text: string): string | null {
  const t = text.trim();
  switch (spec.kind) {
    case "int": {
      if (!INT.test(t)) return `${spec.label}: enter a whole number.`;
      const n = Number(t);
      return n < (spec.min ?? 0) || n > (spec.max ?? 9999) ? `${spec.label}: use a number from ${spec.min} to ${spec.max}.` : null;
    }
    case "money":
      return MONEY.test(t) ? null : `${spec.label}: enter an amount such as 100 or 100.50 (0 switches it off).`;
    case "choice":
      return spec.choices?.some((c) => c.value === t) ? null : `${spec.label}: choose one of the options.`;
    case "text":
      return t.length > (spec.maxLength ?? 200) ? `${spec.label}: at most ${spec.maxLength} characters.` : null;
  }
}

export function toForm(values: Record<string, string | number>): Record<string, string> {
  return Object.fromEntries(FIELDS.map((f) => [f.key, String(values[f.key] ?? "")]));
}

/** Only the settings the person actually changed, ready to send. */
export function changesFrom(form: Record<string, string>, current: Record<string, string | number>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of FIELDS) {
    const now = normalize(f, form[f.key] ?? "");
    const was = normalize(f, String(current[f.key] ?? ""));
    if (now !== was) out[f.key] = now;
  }
  return out;
}

export function formProblems(form: Record<string, string>): string[] {
  return FIELDS.map((f) => fieldProblem(f, form[f.key] ?? "")).filter((p): p is string => p !== null);
}

/** "Standard: Rs 0" style text for the line under each field. */
export function defaultText(spec: FieldSpec, value: string | number | undefined): string {
  if (value === undefined || value === "") return "not set";
  if (spec.kind === "choice") return spec.choices?.find((c) => c.value === value)?.label ?? String(value);
  if (spec.kind === "money") return `Rs ${normalize(spec, String(value)).replace(/\.00$/, "")}`;
  return String(value);
}
