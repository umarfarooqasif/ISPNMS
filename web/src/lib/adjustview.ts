/** Adjustments, credits and refunds. Money is handled as exact strings, never as floating point. */

import { amountProblem } from "./billingview";
import { sumMoney } from "./format";
import { balanceText, isNegative } from "./history";

export type AdjustKind = "credit" | "charge";

export const KIND_LABEL: Record<AdjustKind, string> = {
  credit: "Give a credit or discount (they owe less)",
  charge: "Add a charge (they owe more)",
};

function reasonProblem(reason: string): string | null {
  const r = reason.trim();
  if (r.length < 3) return "Please say why (at least 3 characters).";
  return r.length > 300 ? "The reason is too long." : null;
}

export function adjustProblem(amount: string, reason: string): string | null {
  return amountProblem(amount) ?? reasonProblem(reason);
}

/** A credit is stored as a negative amount, a charge as a positive one. */
export function signedAmount(kind: AdjustKind, amount: string): string {
  const a = amount.trim();
  return kind === "credit" ? `-${a}` : a;
}

export function adjustBody(customerId: string, kind: AdjustKind, amount: string, reason: string) {
  return { customer_id: customerId, amount: signedAmount(kind, amount), reason: reason.trim() };
}

/** What the balance will be after the adjustment, in words. */
export function balanceAfter(balance: string, kind: AdjustKind, amount: string): string {
  return balanceText(sumMoney([balance, signedAmount(kind, amount)]));
}

/** True when `amount` is more than `limit` (both money strings). */
export function exceeds(amount: string, limit: string): boolean {
  return isNegative(sumMoney([limit, `-${amount.trim()}`]));
}

export function refundProblem(amount: string, reason: string, credit: string): string | null {
  const a = amountProblem(amount);
  if (a) return a;
  if (exceeds(amount, credit)) return "You can only pay back the credit the customer actually has.";
  return reasonProblem(reason);
}

export function refundBody(customerId: string, amount: string, reason: string) {
  return { customer_id: customerId, amount: amount.trim(), reason: reason.trim() };
}
