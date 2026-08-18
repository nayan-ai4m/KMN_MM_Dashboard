import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { HmiTooltip, Panel } from "./primitives";
import { usePolledJson } from "@/lib/usePolledJson";

type RecycleLatest = {
  time: string | null;
  fringeMass: number | null;
  barMass: number | null;
  soapMass: number | null;
};

const SLICES = [
  { key: "fringeMass", name: "Fringe", color: "var(--hmi-hard)" },
  { key: "soapMass", name: "Soap", color: "var(--hmi-c3)" },
  { key: "barMass", name: "Bar", color: "var(--hmi-c1)" },
] as const;

const RAD = Math.PI / 180;

function SliceLabel({
  cx,
  cy,
  midAngle,
  outerRadius,
  name,
  value,
  fill,
}: {
  cx?: number;
  cy?: number;
  midAngle?: number;
  outerRadius?: number;
  name?: string;
  value?: number;
  fill?: string;
}) {
  if (cx == null || cy == null || midAngle == null || outerRadius == null || value == null) return null;
  const r = outerRadius + 14;
  const x = cx + r * Math.cos(-midAngle * RAD);
  const y = cy + r * Math.sin(-midAngle * RAD);
  return (
    <text
      x={x}
      y={y}
      fill={fill}
      textAnchor={x > cx ? "start" : "end"}
      dominantBaseline="central"
      className="hmi-donut-label"
    >
      {name}: {value.toFixed(2)} kg
    </text>
  );
}

export function RecycleSection() {
  const latest = usePolledJson<RecycleLatest>("/api/recycle/latest", 30_000, {
    time: null,
    fringeMass: null,
    barMass: null,
    soapMass: null,
  });

  const data = SLICES.map((s) => ({ name: s.name, value: latest[s.key] ?? 0, color: s.color })).filter(
    (d) => d.value > 0,
  );
  const total = data.reduce((sum, d) => sum + d.value, 0);

  return (
    <Panel
      area="hmi-area-recycle"
      title="Recycle Material"
      sub="Mass composition"
      right={latest.time ? <span className="hmi-donut-latest">Latest · {latest.time}</span> : undefined}
    >
      <div className="hmi-chart hmi-donut-wrap">
        {total > 0 ? (
          <>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart margin={{ top: 18, right: 82, bottom: 18, left: 82 }}>
                <Pie
                  data={data}
                  dataKey="value"
                  nameKey="name"
                  innerRadius="58%"
                  outerRadius="86%"
                  paddingAngle={2}
                  stroke="none"
                  label={<SliceLabel />}
                  labelLine={false}
                  isAnimationActive={false}
                >
                  {data.map((d) => (
                    <Cell key={d.name} fill={d.color} />
                  ))}
                </Pie>
                {/* <Tooltip content={<HmiTooltip unit=" kg" />} /> */}
              </PieChart>
            </ResponsiveContainer>
            <div className="hmi-donut-center">
              <div className="hmi-donut-center-label">Total Mass</div>
              <div className="hmi-donut-center-value">{total.toFixed(2)} kg</div>
            </div>
          </>
        ) : (
          <div className="hmi-donut-empty">No recycle data</div>
        )}
      </div>
    </Panel>
  );
}
