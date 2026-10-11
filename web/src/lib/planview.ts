/** Changing a connection's package or price. */

import { validAmount } from "./billingview";

export type PlanService = "INTERNET" | "CABLE";

/** The services a connection actually has. */
export function servicesFor(connectionType: string): PlanService[] {
  if (connectionType === "CABLE") return ["CABLE"];
  if (connectionType === "COMBINED") return ["INTERNET", "CABLE"];
  return ["INTERNET"];
}

export interface PlanForm { service: PlanService; packageId: string; price: string; reason: string }

export function planProblems(f: PlanForm): string[] {
  const out: string[] = [];
  if (!f.packageId && !f.price.trim()) out.push("Choose a package or enter a price.");
  if (f.price.trim() && !validAmount(f.price)) out.push("The price must be an amount like 1500 or 1500.50.");
  if (f.reason.trim().length < 3) out.push("Please say why (at least 3 characters).");
  return out;
}

export function planBody(f: PlanForm): Record<string, unknown> {
  const body: Record<string, unknown> = { service: f.service, reason: f.reason.trim() };
  if (f.packageId) body.package_id = f.packageId;
  if (f.price.trim()) body.price = f.price.trim();
  return body;
}

/** A special price on the connection overrides any package price, so the change would have no effect. */
export function overrideWarning(monthlyPriceOverride: string | null): string | null {
  return monthlyPriceOverride
    ? "This connection has a special monthly price that overrides the package, so the next bill will not change. Remove the special price first."
    : null;
}
