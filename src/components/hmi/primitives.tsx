import type { ReactNode } from "react";

export function Panel({
  title,
  sub,
  right,
  area,
  children,
}: {
  title: string;
  sub?: string;
  right?: ReactNode;
  area: string;
  children: ReactNode;
}) {
  return (
    <section className={`hmi-panel ${area}`}>
      <header className="hmi-panel-head">
        <div style={{ minWidth: 0 }}>
          <h2 className="hmi-panel-title">{title}</h2>
          {sub ? <div className="hmi-panel-sub">{sub}</div> : null}
        </div>
        {right}
      </header>
      <div className="hmi-body">{children}</div>
    </section>
  );
}

export type Tone = "run" | "fault" | "warn" | "idle";

export function StatusPill({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className={`hmi-pill is-${tone}`}>
      <span className="hmi-dot" />
      {label}
    </span>
  );
}

export function KpiTile({
  label,
  value,
  unit,
  tone,
}: {
  label: string;
  value: string | number;
  unit?: string;
  tone?: Tone | "soft" | "hard";
}) {
  return (
    <div className={`hmi-tile${tone ? ` is-${tone}` : ""}`}>
      <div className="hmi-tile-label">{label}</div>
      <div className="hmi-tile-value">
        {value}
        {unit ? <span className="hmi-tile-unit">{unit}</span> : null}
      </div>
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="hmi-legend">
      {items.map((i) => (
        <span key={i.label} className="hmi-legend-item" style={{ color: i.color }}>
          <span className="hmi-swatch" />
          <span style={{ color: "var(--hmi-text-dim)" }}>{i.label}</span>
        </span>
      ))}
    </div>
  );
}

type TooltipPayload = { name?: string; value?: number | string; color?: string; dataKey?: string };

export function HmiTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string | number;
  unit?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="hmi-tooltip">
      <div className="hmi-tooltip-label">{label}</div>
      {payload
        .filter((p) => p.value !== null && p.value !== undefined)
        .map((p) => (
          <div key={p.dataKey ?? p.name} style={{ color: p.color }}>
            {p.name}: {typeof p.value === "number" ? p.value.toFixed(2) : p.value}
            {unit}
          </div>
        ))}
    </div>
  );
}

export function TrendArrow({ direction, color }: { direction: "up" | "down"; color: string }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      style={{
        display: "inline-block",
        verticalAlign: "middle",
        marginLeft: 6,
        transform: direction === "up" ? "scaleY(-1)" : undefined,
      }}
    >
      <path
        d="M12 4 V18 M6 12 L12 18 L18 12"
        stroke={color}
        strokeWidth={3.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function hardnessColor(value: number): string {
  if (value <= 0.25) return "var(--hmi-run)";
  if (value <= 0.5) return "var(--hmi-warn)";
  return "var(--hmi-fault)";
}

export function hardnessLabel(value: number): "SOFT" | "HARD" {
  return value > 0.5 ? "HARD" : "SOFT";
}

export const AXIS = {
  stroke: "rgba(140,170,210,0.35)",
  tick: { fill: "#61708a", fontSize: 10, fontFamily: "var(--hmi-mono)" },
};
