/** Logic behind the billing and payment screens, free of React so it can be tested. */

import type { RunItem } from "./types";
import { isPositiveMoney } from "./format";

export const OUTCOME_LABEL: Record<string, string> = {
  INVOICED: "Billed",
  FREE_SKIPPED: "Free or trial (no charge)",
  ZERO_PRICE: "Not billed: no usable price",
  CYCLES_SKIPPED: "Missed months left out",
  NO_DUE_DATE: "Not billed: no due date",
  LATE_FEE: "Late fee",
  ERROR: "Failed",
};

/** Outcomes that need a person to fix something, in the order to look at them. */
export const ATTENTION_OUTCOMES = ["ERROR", "ZERO_PRICE", "NO_DUE_DATE", "CYCLES_SKIPPED"];

export function outcomeNeedsAttention(outcome: string): boolean {
  return ATTENTION_OUTCOMES.includes(outcome);
}

export const METHOD_LABEL: Record<string, string> = {
  CASH: "Cash (office)",
  COLLECTOR_CASH: "Cash (collector)",
  BANK: "Bank transfer",
  JAZZCASH: "JazzCash",
  EASYPAISA: "Easypaisa",
  CARD: "Card",
  QR: "QR",
};

export const OFFICE_METHODS = ["CASH", "BANK", "JAZZCASH", "EASYPAISA", "CARD", "QR"];

/** One plain sentence describing a (preview or real) run. */
export function runHeadline(r: {
  invoices_created: number; counts: Record<string, number>; behind_connections: number; skipped_cycles: number;
}, dry: boolean): string {
  const bits = [`${r.invoices_created.toLocaleString("en-US")} invoice(s) ${dry ? "would be created" : "created"}`];
  const bad = ATTENTION_OUTCOMES.reduce((n, k) => n + (r.counts[k] ?? 0), 0);
  if (bad > 0) bits.push(`${bad.toLocaleString("en-US")} item(s) need attention`);
  if (r.behind_connections > 0) bits.push(`${r.behind_connections.toLocaleString("en-US")} connection(s) still behind`);
  if (r.skipped_cycles > 0) bits.push(`${r.skipped_cycles.toLocaleString("en-US")} missed month(s) left out`);
  return bits.join(", ");
}

/** A run is only allowed once the person has previewed exactly these settings. */
export interface RunParams {
  runDate: string;
  leadDays: string;
  maxCycles: number;
  skipRemaining: boolean;
}

export function paramsKey(p: RunParams): string {
  return JSON.stringify([p.runDate, p.leadDays.trim(), p.maxCycles, p.skipRemaining]);
}

export function toRunBody(p: RunParams): Record<string, unknown> {
  const body: Record<string, unknown> = { max_cycles: p.maxCycles, skip_remaining: p.skipRemaining };
  if (p.runDate) body.run_date = p.runDate;
  const lead = p.leadDays.trim();
  if (lead !== "") body.lead_days = Number(lead);
  return body;
}

/** Why the form cannot be used yet, or null when it is fine. */
export function runParamsProblem(p: RunParams): string | null {
  if (p.leadDays.trim() !== "" && !/^\d{1,2}$/.test(p.leadDays.trim())) return "Days ahead must be a whole number from 0 to 60.";
  if (p.leadDays.trim() !== "" && Number(p.leadDays) > 60) return "Days ahead must be 60 or less.";
  if (!Number.isInteger(p.maxCycles) || p.maxCycles < 1 || p.maxCycles > 12) return "Months to bill must be between 1 and 12.";
  if (p.runDate && !/^\d{4}-\d{2}-\d{2}$/.test(p.runDate)) return "Enter the date as year-month-day.";
  return null;
}

export function itemsByOutcome(items: RunItem[], outcome: string): RunItem[] {
  return outcome ? items.filter((i) => i.outcome === outcome) : items;
}

// ------------------------------------------------------------------ amounts

const AMOUNT = /^\d{1,10}(\.\d{1,2})?$/;

/** A money amount typed by a person: plain digits with up to two decimals, greater than zero. */
export function validAmount(text: string): boolean {
  const t = text.trim();
  return AMOUNT.test(t) && isPositiveMoney(t);
}

export function amountProblem(text: string): string | null {
  const t = text.trim();
  if (!t) return "Enter the amount.";
  if (!AMOUNT.test(t)) return "Use digits only, with at most two decimals (for example 1500 or 1500.50).";
  if (!isPositiveMoney(t)) return "The amount must be more than zero.";
  return null;
}

// ------------------------------------------------------------------ opening balances CSV

export interface OpeningRowIn {
  wasooli_id: string;
  amount: string;
  note?: string;
}

export interface CsvParse {
  rows: OpeningRowIn[];
  problems: { line: number; text: string }[];
}

/** Splits one CSV line, honouring "quoted, values". */
export function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cur += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { out.push(cur); cur = ""; }
    else cur += ch;
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

/**
 * Reads pasted text: a header row `wasooli_id,amount[,note]` then one customer per line.
 * Anything wrong is reported with its line number and skipped, never guessed.
 */
export function parseOpeningBalanceCsv(text: string): CsvParse {
  const lines = text.replace(/\r/g, "").split("\n");
  const result: CsvParse = { rows: [], problems: [] };
  let headerSeen = false;
  let cols: { id: number; amount: number; note: number } = { id: 0, amount: 1, note: 2 };
  lines.forEach((raw, idx) => {
    const line = raw.trim();
    if (!line) return;
    const cells = splitCsvLine(line);
    if (!headerSeen) {
      headerSeen = true;
      const lower = cells.map((c) => c.toLowerCase());
      const id = lower.indexOf("wasooli_id");
      const amount = lower.indexOf("amount");
      if (id === -1 || amount === -1) {
        result.problems.push({ line: idx + 1, text: "The first line must be a header with at least: wasooli_id,amount" });
        cols = { id: -1, amount: -1, note: -1 }; // read nothing below a bad header
        return;
      }
      cols = { id, amount, note: lower.indexOf("note") };
      return;
    }
    if (cols.id === -1) return;
    const id = cells[cols.id] ?? "";
    const amount = cells[cols.amount] ?? "";
    if (!id) { result.problems.push({ line: idx + 1, text: "Missing wasooli_id" }); return; }
    if (!validAmount(amount)) {
      result.problems.push({ line: idx + 1, text: `Amount "${amount}" is not a valid amount greater than zero` });
      return;
    }
    const note = cols.note >= 0 ? cells[cols.note] : "";
    result.rows.push({ wasooli_id: id, amount: amount.trim(), ...(note ? { note } : {}) });
  });
  if (!headerSeen) result.problems.push({ line: 1, text: "Paste your list here (header row first)" });
  return result;
}
