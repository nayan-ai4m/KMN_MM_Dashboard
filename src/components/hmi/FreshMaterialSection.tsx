import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip } from "recharts";
import { Panel } from "./primitives";
import { usePolledJson } from "@/lib/usePolledJson";

type FreshMaterialPoint = {
  startTime: string | null;
  endTime: string | null;
  durRan: number | null;
  kgAdded: number | null;
  hardness: number | null;
};

type TrendMetric = "durRan" | "kgAdded" | "hardness";

type TrendConfig = {
  key: TrendMetric;
  label: string;
  unit?: string;
  color: string;
  decimals: number;
};

const TRENDS: TrendConfig[] = [
  { key: "durRan", label: "Noodler Duration", unit: "s", color: "var(--hmi-c1)", decimals: 0 },
  { key: "kgAdded", label: "New Material Added", unit: "kg", color: "var(--hmi-c2)", decimals: 1 },
  { key: "hardness", label: "New Material Hardness", color: "var(--hmi-c3)", decimals: 3 },
];

type BarDatum = { i: number; value: number; startTime: string | null; endTime: string | null };

function TrendTooltip({
  active,
  payload,
  config,
}: {
  active?: boolean;
  payload?: { payload: BarDatum }[];
  config: TrendConfig;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="hmi-tooltip">
      <div className="hmi-tooltip-label">{d.startTime && d.endTime ? `${d.startTime} to ${d.endTime}` : "—"}</div>
      <div style={{ color: config.color }}>
        {config.label}: {d.value.toFixed(config.decimals)}
        {config.unit ?? ""}
      </div>
    </div>
  );
}

function TrendRow({ config, data }: { config: TrendConfig; data: FreshMaterialPoint[] }) {
  const bars: BarDatum[] = data.map((d, i) => ({
    i,
    value: d[config.key] ?? 0,
    startTime: d.startTime,
    endTime: d.endTime,
  }));
  const latestPoint = data.length > 0 ? data[data.length - 1] : null;
  const latest = latestPoint ? latestPoint[config.key] : null;

  return (
    <div className="hmi-trend-row">
      <div className="hmi-trend-value">
        <div className="hmi-tile-label">{config.label}</div>
        <div className="hmi-tile-value">
          {latest != null ? latest.toFixed(config.decimals) : "—"}
          {config.unit ? <span className="hmi-tile-unit">{config.unit}</span> : null}
        </div>
        {/* {config.key === "durRan" && latestPoint?.startTime && latestPoint?.endTime ? (
          <div className="hmi-trend-range">
            {latestPoint.startTime} to {latestPoint.endTime}
          </div>
        ) : null} */}
      </div>
      <div className="hmi-trend-chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bars} margin={{ top: 16, right: 4, bottom: 0, left: 4 }}>
            <Tooltip content={<TrendTooltip config={config} />} cursor={{ fill: "rgba(255,255,255,0.06)" }} />
            <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              <LabelList
                dataKey="value"
                position="top"
                formatter={(v: number) => v.toFixed(config.decimals)}
                fill="var(--hmi-text)"
                fontSize={10}
              />
              {bars.map((b) => (
                <Cell key={b.i} fill={config.color} opacity={b.i === bars.length - 1 ? 1 : 0.45} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function FreshMaterialSection() {
  const data = usePolledJson<FreshMaterialPoint[]>("/api/fresh-material/recent?limit=10", 10_000, []);
  const latestPoint = data.length > 0 ? data[data.length - 1] : null;

  return (
    <Panel
      area="hmi-area-fresh"
      title="New Material "
      sub="last 10 cycles"
      right={
        latestPoint?.startTime && latestPoint?.endTime ? (
          <span className="hmi-donut-latest">
            Latest · {latestPoint.startTime} to {latestPoint.endTime}
          </span>
        ) : undefined
      }
    >
      {TRENDS.map((config) => (
        <TrendRow key={config.key} config={config} data={data} />
      ))}
    </Panel>
  );
}
