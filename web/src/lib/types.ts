/** Shapes returned by the billing API (money and ids arrive as strings). */

export interface Me {
  id: string;
  username: string;
  full_name: string;
  roles: string[];
  permissions: string[];
}

export interface Area {
  id: string;
  name: string;
  name_ur: string | null;
  code: string | null;
}

export interface Customer {
  id: string;
  customer_code: string;
  full_name: string;
  full_name_ur: string | null;
  father_name: string | null;
  cnic_masked: string | null;
  mobile: string | null;
  whatsapp: string | null;
  alt_contact: string | null;
  address: string | null;
  address_ur: string | null;
  area_id: string | null;
  house_no: string | null;
  notes: string | null;
  status: string;
  created_at: string;
}

export interface ServiceLine {
  service: string;
  package_id: string | null;
  price: string | null;
}

export interface Connection {
  id: string;
  customer_id: string;
  connection_code: string;
  internet_id: string | null;
  username: string | null;
  connection_type: string;
  install_date: string | null;
  next_due_date: string | null;
  status: string;
  monthly_price_override: string | null;
  service_lines: ServiceLine[];
}

export interface InvoiceLine {
  id: string;
  charge_type: string;
  description: string | null;
  amount: string;
}

export interface Invoice {
  id: string;
  invoice_number: string;
  issue_date: string;
  due_date: string;
  period: string | null;
  total: string;
  paid: string;
  outstanding: string;
  status: string;
  lines: InvoiceLine[];
}

export interface Statement {
  customer_id: string;
  billing_status: string | null;
  balance: string;
  amount_due: string;
  credit: string;
  open_invoices: Invoice[];
}

export interface OutstandingRow {
  customer_id: string;
  customer_code: string;
  full_name: string;
  mobile: string | null;
  balance: string;
  oldest_due_date: string | null;
  days_overdue: number;
  billing_status: string;
}

export interface BillingRun {
  id: string;
  kind: string;
  run_date: string;
  invoices_created: number;
  total_billed: string;
  created_at: string;
}

// ------------------------------------------------------------------ import

export interface ImportSummary {
  error?: string;
  rows_by_status?: Record<string, number>;
  issue_counts?: Record<string, number>;
  connection_status?: Record<string, number>;
  connection_type?: Record<string, number>;
  packages_to_create?: Record<string, number>;
  areas_to_create?: string[];
  monthly_charge_total?: string;
  [key: string]: unknown;
}

export interface ImportSession {
  id: string;
  source_system: string;
  file_name: string;
  file_size: number;
  status: string;
  parser_version: string | null;
  summary: ImportSummary | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface RowIssue {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
}

export interface MatchCandidate {
  kind: "customer" | "same_file" | "connection" | "changes";
  customer_id?: string;
  customer_code?: string;
  name?: string;
  wasooli_id?: string;
  row_index?: number;
  connection_code?: string;
  changes?: unknown;
}

export interface ImportRow {
  id: string;
  page: number | null;
  row_index: number;
  status: string;
  raw_cells: Record<string, string> | null;
  normalized: Record<string, unknown> | null;
  issues: RowIssue[] | null;
  match_candidates: MatchCandidate[] | null;
  result_customer_id: string | null;
  result_connection_id: string | null;
}

export type Decision = "IMPORT" | "SKIP" | "UPDATE_EXISTING" | "CREATE_SEPARATE" | "MANUAL_EDIT";

export interface CommitResult {
  dry_run: boolean;
  actions: Record<string, number>;
  packages_to_create?: string[];
  areas_to_create?: string[];
  result?: Record<string, number>;
}

// ------------------------------------------------------------------ billing and payments (stage 2)

export interface RunItem {
  customer_id: string;
  customer_name: string | null;
  customer_code: string | null;
  connection_id: string | null;
  cycle_due_date: string | null;
  outcome: string;
  amount: string;
  invoice_id: string | null;
  message: string | null;
}

export interface RunResult {
  dry_run: boolean;
  run_id: string | null;
  invoices_created: number;
  total_billed: string;
  counts: Record<string, number>;
  behind_connections: number;
  skipped_cycles: number;
  items: RunItem[];
  items_truncated: boolean;
}

export interface BillingRunFull extends BillingRun {
  params: Record<string, unknown> | null;
  summary: { counts?: Record<string, number>; behind_connections?: number; skipped_cycles?: number } | null;
  created_by: string | null;
}

export interface SuspensionCandidate {
  customer_id: string;
  full_name: string;
  oldest_due_date: string;
  days_overdue: number;
  outstanding: string;
  connection_ids: string[];
}

export interface OpeningBalanceResult {
  index: number;
  status: string;
  customer_id: string | null;
  invoice_id: string | null;
  message: string | null;
}

export interface OpeningBalanceLoad {
  dry_run: boolean;
  counts: Record<string, number>;
  results: OpeningBalanceResult[];
}

export interface Allocation {
  invoice_id: string;
  amount: string;
}

export interface Payment {
  id: string;
  customer_id: string;
  amount: string;
  method: string;
  status: string;
  collector_id: string | null;
  client_txn_id: string | null;
  client_receipt_no: string | null;
  customer_name: string | null;
  customer_code: string | null;
  collected_at: string;
  received_at: string;
  receipt_number: string | null;
  receipt_status: string | null;
  allocations: Allocation[];
  unallocated: string;
  balance: string;
  replayed: boolean;
  void_reason: string | null;
}
