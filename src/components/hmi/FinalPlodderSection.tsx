import { useCallback, useMemo } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS, HmiTooltip, KpiTile, Legend, Panel, StatusPill } from "./primitives";
import { drift, nowLabel, pvEstimationSeries, useLiveSeries, type Point } from "@/lib/hmi-mock";

export function FinalPlodderSection({ coneTemp }: { coneTemp: number }) {
  const initial = useMemo(() => pvEstimationSeries(), []);
  const next = useCallback((prev: Point): Point => {
    const pv = drift(Number(prev["pv"]), 2, 72, 88);
    const spread = +(1.6 + Math.random() * 2.4).toFixed(2);
    return {
      t: nowLabel(),
      pv,
      range: [+(pv - spread).toFixed(2), +(pv + spread).toFixed(2)],
      band: +(spread * 2).toFixed(2),
    };
  }, []);
  const data = useLiveSeries(initial, next, 1700);
  const tone = coneTemp > 74 ? "warn" : "run";

  return (
    <Panel
      area="hmi-area-final"
      title="Final Plodder"
      sub="Layer 03 · Estimation"
      right={<StatusPill tone="run" label="Estimating" />}
    >
      <div className="hmi-split">
        <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: "6px" }}>
          <Legend
            items={[
              { label: "PV Estimate", color: "var(--hmi-c3)" },
              { label: "Min–Max Band", color: "rgba(33,243,122,0.45)" },
            ]}
          />
          <div className="hmi-chart">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
                <defs>
                  <linearGradient id="hmiBand" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--hmi-c3)" stopOpacity={0.34} />
                    <stop offset="100%" stopColor="var(--hmi-c3)" stopOpacity={0.1} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(140,170,210,0.10)" vertical={false} />
                <XAxis dataKey="t" stroke={AXIS.stroke} tick={AXIS.tick} minTickGap={44} tickLine={false} />
                <YAxis
                  stroke={AXIS.stroke}
                  tick={AXIS.tick}
                  tickLine={false}
                  width={44}
                  type="number"
                  domain={[65, 95]}
                  ticks={[65, 75, 85, 95]}
                  allowDataOverflow
                  includeHidden
                />

                <Tooltip content={<HmiTooltip unit=" PV" />} cursor={{ stroke: "rgba(255,255,255,0.18)" }} />
                <Area
                  dataKey="range" baseValue={65}
                  name="Min–Max"
                  stroke="rgba(33,243,122,0.35)"
                  strokeWidth={1}
                  fill="url(#hmiBand)"
                  isAnimationActive={false}
                />

                <Line type="monotone" dataKey="pv" name="PV Estimate" stroke="var(--hmi-c3)" strokeWidth={2.4} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="hmi-side">
          <KpiTile label="Cone Heater Temp" value={coneTemp.toFixed(1)} unit="°C" tone={tone} />
          <KpiTile label="PV Estimate" value={Number(data[data.length - 1]?.["pv"] ?? 0).toFixed(1)} />
          <KpiTile
            label="Band Width"
            value={Number(data[data.length - 1]?.["band"] ?? 0).toFixed(2)}
            unit="PV"
          />
        </div>
      </div>
    </Panel>
  );
}
