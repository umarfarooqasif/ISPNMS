/** Date ranges and file names for the reports screen. Pure, so they are easy to test. */

export type Preset = "today" | "last7" | "month" | "lastMonth" | "last30" | "year";

export const PRESETS: { id: Preset; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "last7", label: "Last 7 days" },
  { id: "last30", label: "Last 30 days" },
  { id: "month", label: "This month" },
  { id: "lastMonth", label: "Last month" },
  { id: "year", label: "This year" },
];

const iso = (d: Date) => d.toISOString().slice(0, 10);
const utc = (s: string) => new Date(`${s}T00:00:00Z`);
const addDays = (d: Date, n: number) => new Date(d.getTime() + n * 86_400_000);

/** The viewer's local calendar day as YYYY-MM-DD (never shifted by timezone maths). */
export function localIsoDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Inclusive start and end dates for a preset, given today as YYYY-MM-DD. */
export function presetRange(preset: Preset, today: string): { from: string; to: string } {
  const t = utc(today);
  switch (preset) {
    case "today":
      return { from: today, to: today };
    case "last7":
      return { from: iso(addDays(t, -6)), to: today };
    case "last30":
      return { from: iso(addDays(t, -29)), to: today };
    case "month":
      return { from: `${today.slice(0, 7)}-01`, to: today };
    case "lastMonth": {
      const firstThis = utc(`${today.slice(0, 7)}-01`);
      const lastPrev = addDays(firstThis, -1);
      return { from: `${iso(lastPrev).slice(0, 7)}-01`, to: iso(lastPrev) };
    }
    case "year":
      return { from: `${today.slice(0, 4)}-01-01`, to: today };
  }
}

export const MAX_RANGE_DAYS = 366;

/** Why a custom range cannot be used, or null. The server checks the same rules. */
export function rangeProblem(from: string, to: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) return "Choose both dates.";
  if (to < from) return "The end date is before the start date.";
  const days = Math.round((utc(to).getTime() - utc(from).getTime()) / 86_400_000) + 1;
  return days > MAX_RANGE_DAYS ? `Choose a range of at most ${MAX_RANGE_DAYS} days.` : null;
}

export type ExportName = "payments" | "invoices" | "outstanding" | "customers";

export const EXPORTS: { name: ExportName; label: string; ranged: boolean; hint: string }[] = [
  { name: "payments", label: "Payments", ranged: true, hint: "Every payment in the dates above, including cancelled ones (marked VOID)." },
  { name: "invoices", label: "Bills", ranged: true, hint: "Every bill issued in the dates above, with paid and owed." },
  { name: "outstanding", label: "Who owes money", ranged: false, hint: "Everyone with an unpaid balance right now." },
  { name: "customers", label: "Customer list", ranged: false, hint: "All customers with connections and balance. The CNIC is never included." },
];

export function exportPath(name: ExportName, from?: string, to?: string): string {
  const ranged = EXPORTS.find((e) => e.name === name)?.ranged;
  const q = ranged && from && to ? `?date_from=${from}&date_to=${to}` : "";
  return `/reports/export/${name}.csv${q}`;
}

export function exportFilename(name: ExportName, from?: string, to?: string): string {
  const ranged = EXPORTS.find((e) => e.name === name)?.ranged;
  return ranged && from && to ? `${name}_${from}_to_${to}.csv` : `${name}.csv`;
}
