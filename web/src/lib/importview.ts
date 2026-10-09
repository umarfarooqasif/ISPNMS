/** Logic behind the import screens, kept free of React so it is easy to test. */

import type { ImportRow, ImportSession, ImportSummary, MatchCandidate } from "./types";

/** Statuses during which the server is still working, so the page keeps checking. */
export const BUSY_SESSION = ["UPLOADED", "PARSED", "IMPORTING"];

export function isBusy(status: string): boolean {
  return BUSY_SESSION.includes(status);
}

export function canCommit(session: Pick<ImportSession, "status">): boolean {
  return ["MATCHED", "IN_REVIEW", "APPROVED"].includes(session.status);
}

export const STATUS_LABEL: Record<string, string> = {
  NEW: "New customer",
  DUPLICATE: "Already in the system",
  UPDATED: "Already there, details changed",
  ERROR: "Cannot import",
  REVIEW: "Needs your decision",
  IMPORTED: "Imported",
  SKIPPED: "Skipped",
};

export const SESSION_LABEL: Record<string, string> = {
  UPLOADED: "Uploaded, reading the file…",
  PARSED: "Read, checking against existing customers…",
  MATCHED: "Ready to review",
  IN_REVIEW: "In review",
  APPROVED: "Approved",
  IMPORTING: "Importing…",
  COMPLETED: "Completed",
  FAILED: "Failed",
};

/** Friendly names for the issue codes the file reader raises. Unknown codes show as they are. */
export const ISSUE_LABEL: Record<string, string> = {
  NO_MOBILE: "No mobile number",
  INVALID_MOBILE: "Mobile number looks wrong",
  AREA_INFERRED: "Area guessed from the address",
  AREA_UNKNOWN: "Area could not be found",
  NO_AREA: "Address has no area",
  ZERO_PRICE_ACTIVE: "Active customer with a zero price",
  ZERO_LINE_PRICE: "One service has no price",
  RECHARGE_BEFORE_INSTALL: "Recharge date before install date",
  BAD_INSTALL_DATE: "Install date unreadable",
  BAD_RECHARGE_DATE: "Recharge date unreadable",
  TOTAL_MISMATCH: "Total does not match the prices",
  BAD_AMOUNT: "An amount is invalid",
  NO_SERVICE: "No cable or internet package",
  MISSING_ID: "Row has no ID",
  MISSING_NAME: "Row has no name",
};

export function issueLabel(code: string): string {
  return ISSUE_LABEL[code] ?? code;
}

export interface SummaryView {
  rowsByStatus: Record<string, number>;
  totalRows: number;
  issueCounts: [string, number][];
  connectionStatus: Record<string, number>;
  connectionType: Record<string, number>;
  packagesToCreate: [string, number][];
  areasToCreate: string[];
  monthlyChargeTotal: string | null;
  error: string | null;
}

/** Reads the server's summary defensively: a missing part never breaks the page. */
export function summaryView(summary: ImportSummary | null | undefined): SummaryView {
  const s = summary ?? {};
  const rowsByStatus = s.rows_by_status ?? {};
  const byCountDesc = (a: [string, number], b: [string, number]) => b[1] - a[1] || a[0].localeCompare(b[0]);
  return {
    rowsByStatus,
    totalRows: Object.values(rowsByStatus).reduce((a, b) => a + b, 0),
    issueCounts: Object.entries(s.issue_counts ?? {}).sort(byCountDesc),
    connectionStatus: s.connection_status ?? {},
    connectionType: s.connection_type ?? {},
    packagesToCreate: Object.entries(s.packages_to_create ?? {}).sort(byCountDesc),
    areasToCreate: s.areas_to_create ?? [],
    monthlyChargeTotal: s.monthly_charge_total ?? null,
    error: typeof s.error === "string" ? s.error : null,
  };
}

/** The tab to open first: whatever needs a human, else the bulk of the file. */
export function defaultRowStatus(rowsByStatus: Record<string, number>): string {
  for (const s of ["REVIEW", "ERROR", "NEW", "UPDATED", "DUPLICATE", "IMPORTED", "SKIPPED"]) {
    if ((rowsByStatus[s] ?? 0) > 0) return s;
  }
  return "NEW";
}

const DECISION_TEXT: Record<string, string> = {
  IMPORT: "will import",
  CREATE_SEPARATE: "will import as new",
  SKIP: "will skip",
  UPDATE_EXISTING: "will attach to existing customer",
  MANUAL_EDIT: "will import with your edits",
};

/** What a saved decision means, in plain words. null when nothing was decided. */
export function decisionLabel(decision: string | null | undefined): string | null {
  if (!decision) return null;
  return DECISION_TEXT[decision] ?? decision;
}

export function rowName(row: ImportRow): string {
  const n = row.normalized?.["full_name"];
  if (typeof n === "string" && n) return n;
  return row.raw_cells?.["Name"] ?? "(no name)";
}

export function rowField(row: ImportRow, key: string): string {
  const v = row.normalized?.[key];
  return typeof v === "string" || typeof v === "number" ? String(v) : "";
}

/** Existing customers a possible-duplicate row could be attached to. */
export function attachableCustomers(row: ImportRow): MatchCandidate[] {
  return (row.match_candidates ?? []).filter((c) => c.kind === "customer" && !!c.customer_id);
}

export function candidateText(c: MatchCandidate): string {
  switch (c.kind) {
    case "customer":
      return `Existing customer ${c.name ?? ""} (${c.customer_code ?? "?"}) has the same mobile and a similar name`;
    case "same_file":
      return `Another row in this file (ID ${c.wasooli_id ?? "?"}, ${c.name ?? ""}) has the same mobile and a similar name`;
    case "connection":
      return `Already imported as connection ${c.connection_code ?? ""}`;
    case "changes":
      return "Some details differ from what is stored";
    default:
      return "";
  }
}

/** What a sensible person must confirm before the real import. */
export function commitWarnings(preview: { areas_to_create?: string[]; packages_to_create?: string[] } | null): string[] {
  if (!preview) return [];
  const out: string[] = [];
  if (preview.areas_to_create?.length) out.push(`${preview.areas_to_create.length} new area(s) will be created`);
  if (preview.packages_to_create?.length) out.push(`${preview.packages_to_create.length} new package(s) will be created`);
  return out;
}

export const ACTION_LABEL: Record<string, string> = {
  create: "New customers to create",
  attach: "Connections to attach to existing customers",
  update: "Existing connections to update",
  skip: "Rows that will be left out",
  review: "Possible duplicates left for you to decide",
  error: "Rows that cannot be imported",
  duplicate: "Already in the system (nothing to do)",
};
