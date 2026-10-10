/** Geometry for the SVG charts. Pure functions, so the maths can be tested without a browser. */

/** Rounds a maximum up to a tidy axis top: 1, 2, 2.5, 5 or 10 times a power of ten. */
export function niceMax(max: number): number {
  if (!(max > 0) || !Number.isFinite(max)) return 1;
  const exp = Math.floor(Math.log10(max));
  const base = 10 ** exp;
  const f = max / base;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nice * base;
}

export function axisTicks(max: number, count = 4): number[] {
  const top = niceMax(max);
  return Array.from({ length: count + 1 }, (_, i) => (top * i) / count);
}

/** 1250000 -> "1.3M", 450000 -> "450K", 800 -> "800". For axis labels only. */
export function shortNumber(n: number): string {
  const abs = Math.abs(n);
  const trim = (x: number) => x.toFixed(1).replace(/\.0$/, "");
  if (abs >= 1_000_000) return `${trim(n / 1_000_000)}M`;
  if (abs >= 1_000) return `${trim(n / 1_000)}K`;
  return String(Math.round(n));
}

/** Show at most `maxLabels` x-axis labels: every n-th one. */
export function labelStep(count: number, maxLabels: number): number {
  return Math.max(1, Math.ceil(count / Math.max(1, maxLabels)));
}

export interface Frame { width: number; height: number; left: number; right: number; top: number; bottom: number }

export const DEFAULT_FRAME: Frame = { width: 640, height: 240, left: 48, right: 12, top: 12, bottom: 28 };

export interface Bar { x: number; y: number; w: number; h: number }

function plot(frame: Frame) {
  return { w: frame.width - frame.left - frame.right, h: frame.height - frame.top - frame.bottom };
}

/** One bar per value. A positive value always gets at least a 1px bar so it never disappears. */
export function barLayout(values: number[], frame: Frame = DEFAULT_FRAME, gap = 0.25) {
  const { w, h } = plot(frame);
  const max = niceMax(Math.max(0, ...values));
  const slot = values.length > 0 ? w / values.length : w;
  const bars: Bar[] = values.map((v, i) => {
    const bh = v > 0 ? Math.max(1, (v / max) * h) : 0;
    return { x: frame.left + i * slot + (slot * gap) / 2, y: frame.top + h - bh, w: Math.max(1, slot * (1 - gap)), h: bh };
  });
  return { bars, max, ticks: axisTicks(max), slot };
}

/** Two bars side by side for each group (billed vs collected). */
export function groupedLayout(a: number[], b: number[], frame: Frame = DEFAULT_FRAME, gap = 0.3) {
  const { w, h } = plot(frame);
  const n = Math.max(a.length, b.length);
  const max = niceMax(Math.max(0, ...a, ...b));
  const slot = n > 0 ? w / n : w;
  const barW = Math.max(1, (slot * (1 - gap)) / 2);
  const make = (values: number[], offset: number): Bar[] =>
    values.map((v, i) => {
      const bh = v > 0 ? Math.max(1, (v / max) * h) : 0;
      return { x: frame.left + i * slot + (slot * gap) / 2 + offset * barW, y: frame.top + h - bh, w: barW, h: bh };
    });
  return { first: make(a, 0), second: make(b, 1), max, ticks: axisTicks(max), slot };
}

/** Width of a horizontal bar as a percentage of the largest value (0 to 100). */
export function percentOfMax(value: number, max: number): number {
  if (!(max > 0) || !(value > 0)) return 0;
  return Math.min(100, Math.max(1, Math.round((value / max) * 100)));
}
