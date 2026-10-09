/** Wording for the customer history and print pages. Pure, so it is easy to test. */

import { money } from "./format";

export const ENTRY_LABEL: Record<string, string> = {
  CHARGE: "Bill",
  DISCOUNT: "Discount",
  PAYMENT: "Payment received",
  PAYMENT_REVERSAL: "Payment cancelled",
  ADJUSTMENT: "Adjustment",
  REFUND: "Refund paid out",
};

export function entryLabel(type: string): string {
  return ENTRY_LABEL[type] ?? type;
}

/** "-500.00" -> "500.00". Strings only, so no rounding can creep in. */
export function absMoney(value: string): string {
  return value.trim().startsWith("-") ? value.trim().slice(1) : value.trim();
}

export function isNegative(value: string): boolean {
  return /^-\s*0*\.?0*[1-9]/.test(value.trim()) || /^-\d*[1-9]/.test(value.trim());
}

/** A ledger amount split into the two columns of a normal statement. */
export function columns(amount: string): { charged: string; credited: string } {
  if (isNegative(amount)) return { charged: "", credited: money(absMoney(amount)) };
  const m = money(amount);
  return { charged: m === "Rs 0" ? "" : m, credited: "" };
}

/** What the running balance means in words. */
export function balanceText(balance: string): string {
  if (isNegative(balance)) return `${money(absMoney(balance))} credit`;
  const m = money(balance);
  return m === "Rs 0" || m === "" ? "Rs 0" : `${m} owed`;
}

/** The wording on a receipt for how a payment was used. */
export function usageText(allocatedTotal: string, unallocated: string): string {
  const parts: string[] = [];
  if (money(allocatedTotal) !== "Rs 0" && money(allocatedTotal) !== "") parts.push(`${money(allocatedTotal)} paid against bills`);
  if (money(unallocated) !== "Rs 0" && money(unallocated) !== "") parts.push(`${money(unallocated)} kept as advance credit`);
  return parts.join(", ") || "Recorded";
}
