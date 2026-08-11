import { useCallback, useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AXIS, HmiTooltip, Legend, Panel, StatusPill } from "./primitives";
import { drift, mixerSeries, nowLabel, useLiveSeries, type Point } from "@/lib/hmi-mock";

export function MixerSection({ batchCount, batchType }: { batchCount: number; batchType: "SOFT" | "HARD" }) {
  const initial = useMemo(() => mixerSeries(), []);
  const next = useCallback(
    (prev: Point): Point => ({
      t: nowLabel(),
      motor1: drift(Number(prev["motor1"]), 6, 48, 76),
      motor2: drift(Number(prev["motor2"]), 5, 42, 68),
    }),
    [],
  );
  const data = useLiveSeries(initial, next);

  return (
    <Panel
      area="hmi-area-mixer"
      title="Mixer"
      sub="Layer 01 · Data"
      right={<StatusPill tone="run" label="Running" />}
    >
      <div className="hmi-hero">
        <div>
          <div className="hmi-tile-label">Batch Count</div>
          <div className="hmi-hero-value">{String(batchCount).padStart(3, "0")}</div>
        </div>
        <div className={`hmi-badge is-${batchType.toLowerCase()}`}>
          <span className="hmi-dot" />
          {batchType}
        </div>
      </div>

      <Legend
        items={[
          { label: "Motor 1", color: "var(--hmi-c1)" },
          { label: "Motor 2", color: "var(--hmi-c2)" },
        ]}
      />

      <div className="hmi-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="rgba(140,170,210,0.10)" vertical={false} />
            <XAxis dataKey="t" stroke={AXIS.stroke} tick={AXIS.tick} minTickGap={40} tickLine={false} />
            <YAxis stroke={AXIS.stroke} tick={AXIS.tick} tickLine={false} width={44} domain={[30, 85]} />
            <Tooltip content={<HmiTooltip unit=" A" />} cursor={{ stroke: "rgba(255,255,255,0.18)" }} />
            <Line
              type="monotone"
              dataKey="motor1"
              name="Motor 1"
              stroke="var(--hmi-c1)"
              strokeWidth={2.2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="motor2"
              name="Motor 2"
              stroke="var(--hmi-c2)"
              strokeWidth={2.2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}
