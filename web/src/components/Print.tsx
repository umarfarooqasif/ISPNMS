"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import type { Company } from "@/lib/types";

export function useCompany(): Company {
  const [c, setC] = useState<Company>({ name: "ISP Billing", phone: "", address: "" });
  useEffect(() => {
    fetch("/company", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j: Company | null) => { if (j) setC(j); })
      .catch(() => { /* keep the default heading */ });
  }, []);
  return c;
}

export type PaperSize = "80mm" | "a4";

/** The page chrome for anything printed: a toolbar that never prints, and the right paper size. */
export function PrintFrame({ children, backHref, sizes, size, onSize }: {
  children: ReactNode;
  backHref: string;
  sizes?: PaperSize[];
  size: PaperSize;
  onSize?: (s: PaperSize) => void;
}) {
  const page = size === "80mm" ? "80mm auto" : "A4";
  const margin = size === "80mm" ? "3mm" : "12mm";
  return (
    <div className={`print-root ${size === "80mm" ? "paper-80" : "paper-a4"}`}>
      <style>{`@page { size: ${page}; margin: ${margin}; }`}</style>
      <div className="no-print print-bar">
        <Link className="btn secondary" href={backHref}>← Back</Link>
        {sizes && sizes.length > 1 ? (
          <select aria-label="Paper size" value={size} onChange={(e) => onSize?.(e.target.value as PaperSize)}>
            {sizes.map((s) => <option key={s} value={s}>{s === "80mm" ? "Thermal receipt (80 mm)" : "A4 page"}</option>)}
          </select>
        ) : null}
        <button className="btn" onClick={() => window.print()}>Print or save as PDF</button>
      </div>
      <div className="print-sheet">{children}</div>
    </div>
  );
}

export function CompanyHeader({ company }: { company: Company }) {
  return (
    <header className="print-head">
      <div className="print-company">{company.name}</div>
      {company.address ? <div>{company.address}</div> : null}
      {company.phone ? <div>{company.phone}</div> : null}
    </header>
  );
}
