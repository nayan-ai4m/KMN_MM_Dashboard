import { Area, CartesianGrid, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS, KpiTile, Legend, Panel, StatusPill } from "./primitives";
import type { Point } from "@/lib/hmi-mock";
import { usePolledJson } from "@/lib/usePolledJson";

type FinalPlodderStatus = { coneTemp: number | null; conePressure: number | null; running: boolean };

function RangeTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value?: [number, number] }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const [min, max] = payload[0]?.value ?? [];
  if (min == null || max == null) return null;
  return (
    <div className="hmi-tooltip">
      <div className="hmi-tooltip-label">{label}</div>
      <div>Estimated Min Value is {min} PV</div>
      <div>Estimated Max Value is {max} PV</div>
    </div>
  );
}

export function FinalPlodderSection() {
  const data = usePolledJson<Point[]>("/api/final-plodder/recent?minutes=10", 10_000, []);
  const status = usePolledJson<FinalPlodderStatus>("/api/final-plodder/status", 10_000, {
    coneTemp: null,
    conePressure: null,
    running: false,
  });
  const tone = status.coneTemp != null && status.coneTemp > 74 ? "warn" : "run";
  const lastRange = data[data.length - 1]?.["range"] as [number, number] | undefined;

  return (
    <Panel
      area="hmi-area-final"
      title="Final Plodder"
      sub="Data · Estimation"
    >
      <div className="hmi-split">
        <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: "6px" }}>
          <Legend items={[{ label: "PV Estimation Min-Max Range", color: "rgba(33,243,122,0.45)" }]} />
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
                  domain={[(dataMin: number) => dataMin - 1, (dataMax: number) => dataMax + 1]}
                />
                <Tooltip content={<RangeTooltip />} cursor={{ stroke: "rgba(255,255,255,0.18)" }} />
                <Area
                  dataKey="range"
                  name="PV Estimation Min-Max Range"
                  stroke="rgba(33,243,122,0.35)"
                  strokeWidth={1}
                  fill="url(#hmiBand)"
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="hmi-side">
         <KpiTile
            label="Estimated PV Range"
            value={lastRange ? `${lastRange[0].toFixed(1)} – ${lastRange[1].toFixed(1)}` : "—"}
            unit="PV"
          />
          <KpiTile
            label="Cone Heater Temp"
            value={status.coneTemp != null ? status.coneTemp.toFixed(1) : "—"}
            unit="°C"
            tone={tone}
          />
          <KpiTile label="Running Status" value={status.running ? "RUNNING" : "STOPPED"} tone={status.running ? "run" : "fault"} />
        </div>
      </div>
    </Panel>
  );
}
