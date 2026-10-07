/** Display helpers. Money is handled as strings, never as floating point. */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "12500.00" -> "Rs 12,500"; "1234.5" -> "Rs 1,234.50"; "-300" -> "-Rs 300". null/invalid -> "". */
export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const s = String(value).trim();
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(s);
  if (!m) return s;
  const [, sign, whole, fracRaw = ""] = m;
  const frac = (fracRaw + "00").slice(0, 2);
  const grouped = whole.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const isZeroFrac = frac === "00";
  const isZero = /^0+$/.test(whole) && isZeroFrac;
  return `${isZero ? "" : sign}Rs ${grouped}${isZeroFrac ? "" : "." + frac}`;
}

/** True when a money string is greater than zero (string compare of digits, no floats). */
export function isPositiveMoney(value: string | null | undefined): boolean {
  if (!value) return false;
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!m) return false;
  return m[1] !== "-" && /[1-9]/.test(m[2] + (m[3] ?? ""));
}

/** "2026-10-04" -> "4 Oct 2026" (no timezone maths, so the day never shifts). */
export function fmtDate(value: string | null | undefined): string {
  if (!value) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return value;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}`;
}

/** An ISO timestamp shown in the viewer's own timezone: "4 Oct 2026, 3:20 PM". */
export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const h = d.getHours();
  const mins = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${h % 12 || 12}:${mins} ${h < 12 ? "AM" : "PM"}`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}
