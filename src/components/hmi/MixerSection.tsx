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
import type { Point } from "@/lib/hmi-mock";
import { usePolledJson } from "@/lib/usePolledJson";

type MixerStatus = { batchCount: number | null; running: boolean };

export function MixerSection({ batchType }: { batchType: "SOFT" | "HARD" }) {
  const data = usePolledJson<Point[]>("/api/mixer/recent?minutes=10", 10_000, []);
  const status = usePolledJson<MixerStatus>("/api/mixer/status", 10_000, { batchCount: null, running: false });

  return (
    <Panel
      area="hmi-area-mixer"
      title="Mixer"
      sub="Data · Estimation"
      right={<StatusPill tone={status.running ? "run" : "fault"} label={status.running ? "Running" : "Stopped"} />}
    >
      <div className="hmi-hero">
        <div>
          <div className="hmi-tile-label">Batch Count</div>
          <div className="hmi-hero-value">
            {status.batchCount != null ? status.batchCount : "—"}
          </div>
        </div>
        <div className={`hmi-badge is-${batchType.toLowerCase()}`}>
          <span className="hmi-dot" />
          {batchType}
        </div>
      </div>

      <Legend
        items={[
          { label: "Current_50HP", color: "var(--hmi-c1)" },
          { label: "Current_60HP", color: "var(--hmi-c2)" },
        ]}
      />

      <div className="hmi-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="rgba(140,170,210,0.10)" vertical={false} />
            <XAxis dataKey="t" stroke={AXIS.stroke} tick={AXIS.tick} minTickGap={40} tickLine={false} />
            <YAxis stroke={AXIS.stroke} tick={AXIS.tick} tickLine={false} width={44} domain={["auto", "auto"]} />
            <Tooltip content={<HmiTooltip unit=" A" />} cursor={{ stroke: "rgba(255,255,255,0.18)" }} />
            <Line
              type="monotone"
              dataKey="Current_50HP"
              name="Current_50HP"
              stroke="var(--hmi-c1)"
              strokeWidth={2.2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="Current_60HP"
              name="Current_60HP"
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
