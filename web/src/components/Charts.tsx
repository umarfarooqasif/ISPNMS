import { DEFAULT_FRAME, barLayout, groupedLayout, labelStep, percentOfMax, shortNumber } from "@/lib/charts";

const FRAME = DEFAULT_FRAME;

function Axes({ ticks, max }: { ticks: number[]; max: number }) {
  const plotH = FRAME.height - FRAME.top - FRAME.bottom;
  return (
    <g>
      {ticks.map((t) => {
        const y = FRAME.top + plotH - (max > 0 ? (t / max) * plotH : 0);
        return (
          <g key={t}>
            <line x1={FRAME.left} x2={FRAME.width - FRAME.right} y1={y} y2={y} stroke="#e1e6eb" />
            <text x={FRAME.left - 6} y={y + 4} textAnchor="end" fontSize="10" fill="#66727f">{shortNumber(t)}</text>
          </g>
        );
      })}
    </g>
  );
}

/** One bar per item, e.g. collections for each of the last 30 days. Hover a bar to see its exact value. */
export function BarChart({ data, label, color = "#0b6e4f" }: {
  data: { label: string; value: number; detail?: string }[];
  label: string;
  color?: string;
}) {
  const { bars, max, ticks, slot } = barLayout(data.map((d) => d.value));
  const step = labelStep(data.length, 8);
  return (
    <svg viewBox={`0 0 ${FRAME.width} ${FRAME.height}`} role="img" aria-label={label} style={{ width: "100%", height: "auto" }}>
      <Axes ticks={ticks} max={max} />
      {bars.map((b, i) => (
        <g key={i}>
          <rect x={b.x} y={b.y} width={b.w} height={b.h} fill={color} rx="2">
            <title>{data[i].detail ?? `${data[i].label}: ${data[i].value}`}</title>
          </rect>
          {i % step === 0 ? (
            <text x={FRAME.left + i * slot + slot / 2} y={FRAME.height - 8} textAnchor="middle" fontSize="10" fill="#66727f">{data[i].label}</text>
          ) : null}
        </g>
      ))}
    </svg>
  );
}

/** Two bars per item, e.g. billed and collected for each month. */
export function GroupedBarChart({ data, label, names, colors = ["#9db8ad", "#0b6e4f"] }: {
  data: { label: string; a: number; b: number; detail?: string }[];
  label: string;
  names: [string, string];
  colors?: [string, string];
}) {
  const g = groupedLayout(data.map((d) => d.a), data.map((d) => d.b));
  const step = labelStep(data.length, 12);
  return (
    <div>
      <div className="small muted" style={{ display: "flex", gap: "1rem", marginBottom: ".25rem" }}>
        {names.map((n, i) => (
          <span key={n}><span style={{ display: "inline-block", width: 10, height: 10, background: colors[i], marginRight: 4, borderRadius: 2 }} />{n}</span>
        ))}
      </div>
      <svg viewBox={`0 0 ${FRAME.width} ${FRAME.height}`} role="img" aria-label={label} style={{ width: "100%", height: "auto" }}>
        <Axes ticks={g.ticks} max={g.max} />
        {data.map((d, i) => (
          <g key={i}>
            <rect x={g.first[i].x} y={g.first[i].y} width={g.first[i].w} height={g.first[i].h} fill={colors[0]} rx="2">
              <title>{d.detail ?? `${d.label}: ${names[0]} ${d.a}`}</title>
            </rect>
            <rect x={g.second[i].x} y={g.second[i].y} width={g.second[i].w} height={g.second[i].h} fill={colors[1]} rx="2">
              <title>{d.detail ?? `${d.label}: ${names[1]} ${d.b}`}</title>
            </rect>
            {i % step === 0 ? (
              <text x={FRAME.left + i * g.slot + g.slot / 2} y={FRAME.height - 8} textAnchor="middle" fontSize="10" fill="#66727f">{d.label}</text>
            ) : null}
          </g>
        ))}
      </svg>
    </div>
  );
}

/** A list of labelled horizontal bars, e.g. money owed by area. */
export function HBars({ rows, color = "#b3261e" }: { rows: { label: string; value: number; text: string; sub?: string }[]; color?: string }) {
  const max = Math.max(0, ...rows.map((r) => r.value));
  if (rows.length === 0) return <p className="muted">Nothing to show.</p>;
  return (
    <div>
      {rows.map((r) => (
        <div key={r.label} style={{ margin: ".4rem 0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: ".5rem" }}>
            <span>{r.label}{r.sub ? <span className="small muted"> · {r.sub}</span> : null}</span>
            <strong>{r.text}</strong>
          </div>
          <div style={{ background: "#eceff2", borderRadius: 4, height: 8 }}>
            <div style={{ width: `${percentOfMax(r.value, max)}%`, background: color, height: 8, borderRadius: 4 }} />
          </div>
        </div>
      ))}
    </div>
  );
}
