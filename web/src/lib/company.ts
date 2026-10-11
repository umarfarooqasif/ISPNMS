import type { Company } from "./types";

export const DEFAULT_COMPANY: Company = { name: "ISP Billing", phone: "", address: "" };

/**
 * The business details printed on receipts. Each field uses what was saved in Settings; if that is
 * blank, the value from the server's configuration file; if that is blank too, a plain default.
 */
export function mergeCompany(saved: Partial<Company> | null | undefined, fromFile: Partial<Company> | null | undefined): Company {
  const pick = (key: keyof Company): string => {
    const a = (saved?.[key] ?? "").trim();
    if (a) return a;
    const b = (fromFile?.[key] ?? "").trim();
    return b || DEFAULT_COMPANY[key];
  };
  return { name: pick("name"), phone: pick("phone"), address: pick("address") };
}
