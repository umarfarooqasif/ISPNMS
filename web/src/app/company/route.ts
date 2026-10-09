import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/** The business details printed at the top of receipts and invoices (set in .env for now). */
export function GET() {
  return NextResponse.json({
    name: process.env.COMPANY_NAME ?? "ISP Billing",
    phone: process.env.COMPANY_PHONE ?? "",
    address: process.env.COMPANY_ADDRESS ?? "",
  });
}
