/** Logic behind the packages and areas screens. Pure, so it is easy to test. */

import { validAmount } from "./billingview";
import type { PackageFull } from "./types";

export interface PackageForm {
  code: string;
  name: string;
  display_name: string;
  display_name_ur: string;
  speed_mbps: string;
  monthly_price: string;
  cable_price: string;
  internet_price: string;
  status: "ACTIVE" | "INACTIVE";
  description: string;
}

export const EMPTY_PACKAGE: PackageForm = {
  code: "", name: "", display_name: "", display_name_ur: "", speed_mbps: "",
  monthly_price: "", cable_price: "", internet_price: "", status: "ACTIVE", description: "",
};

export function formFromPackage(p: PackageFull): PackageForm {
  return {
    code: p.code, name: p.name, display_name: p.display_name, display_name_ur: p.display_name_ur ?? "",
    speed_mbps: p.speed_mbps === null ? "" : String(p.speed_mbps),
    monthly_price: p.monthly_price ?? "", cable_price: p.cable_price ?? "", internet_price: p.internet_price ?? "",
    status: p.status === "INACTIVE" ? "INACTIVE" : "ACTIVE", description: p.description ?? "",
  };
}

/** A price may be left empty, but if typed it must be a proper amount. */
export function optionalAmountProblem(text: string, label: string): string | null {
  const t = text.trim();
  if (t === "") return null;
  if (/^0+(\.0{1,2})?$/.test(t)) return null; // zero is allowed for a free package
  return validAmount(t) ? null : `${label} must be an amount like 1500 or 1500.50.`;
}

export function packageProblems(f: PackageForm, isNew: boolean): string[] {
  const out: string[] = [];
  if (isNew) {
    if (!f.code.trim()) out.push("Enter a short code, for example star3.");
    else if (!/^[A-Za-z0-9_.-]{1,64}$/.test(f.code.trim())) out.push("The code may use only letters, digits, dot, dash and underscore.");
  }
  if (!f.name.trim()) out.push("Enter the package name.");
  if (!f.display_name.trim()) out.push("Enter the name shown to customers.");
  for (const [text, label] of [[f.monthly_price, "The monthly price"], [f.cable_price, "The cable price"], [f.internet_price, "The internet price"]] as const) {
    const p = optionalAmountProblem(text, label);
    if (p) out.push(p);
  }
  if (f.speed_mbps.trim() !== "" && !/^\d{1,5}$/.test(f.speed_mbps.trim())) out.push("The speed must be a whole number of Mbps.");
  return out;
}

export function packageWarning(f: PackageForm): string | null {
  const none = !f.monthly_price.trim() && !f.cable_price.trim() && !f.internet_price.trim();
  return none ? "No price is set. Connections on this package need their own price, or they cannot be billed." : null;
}

const NULLABLE: (keyof PackageForm)[] = ["display_name_ur", "monthly_price", "cable_price", "internet_price", "description"];

/** Create: every filled field. Edit: only what changed, and clearing a field on purpose sends null. */
export function packageBody(f: PackageForm, original?: PackageForm): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  const t = (v: string) => v.trim();
  const put = (key: keyof PackageForm, value: unknown, changed: boolean) => { if (changed) body[key] = value; };

  if (!original) body.code = t(f.code);
  for (const k of ["name", "display_name"] as const) put(k, t(f[k]), !original || t(f[k]) !== t(original[k]));
  for (const k of NULLABLE) {
    const now = t(f[k]);
    if (original) put(k, now === "" ? null : now, now !== t(original[k]));
    else if (now !== "") body[k] = now;
  }
  const speed = t(f.speed_mbps);
  if (original) put("speed_mbps", speed === "" ? null : Number(speed), speed !== t(original.speed_mbps));
  else if (speed !== "") body.speed_mbps = Number(speed);
  put("status", f.status, !original || f.status !== original.status);
  return body;
}

// ------------------------------------------------------------------ areas

export interface AreaForm { name: string; name_ur: string; code: string }

export function areaProblem(f: AreaForm): string | null {
  return f.name.trim() ? null : "Enter the area's name.";
}

export function areaBody(f: AreaForm, original?: AreaForm): Record<string, unknown> {
  const t = (v: string) => v.trim();
  const body: Record<string, unknown> = {};
  if (!original || t(f.name) !== t(original.name)) body.name = t(f.name);
  for (const k of ["name_ur", "code"] as const) {
    const now = t(f[k]);
    if (original) { if (now !== t(original[k])) body[k] = now === "" ? null : now; }
    else if (now !== "") body[k] = now;
  }
  return body;
}

/** Warning shown on the package screen: explicit connection prices ignore the package price. */
export const PRICE_NOTE =
  "Changing a package's price changes what customers are billed only if their connection has no price of its own. " +
  "Customers imported from Wasooli keep the price that was in the file.";
