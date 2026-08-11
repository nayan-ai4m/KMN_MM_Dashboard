import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS, HmiTooltip, Legend, Panel, StatusPill } from "./primitives";
import type { Point } from "@/lib/hmi-mock";
import { usePolledJson } from "@/lib/usePolledJson";

export function TransportSection() {
  const data = usePolledJson<Point[]>("/api/transport/recent?minutes=10", 10_000, []);

  return (
    <Panel
      area="hmi-area-transport"
      title="First Floor Machines"
      sub="Noodler · Conveyor · Roll Mill"
    >
      <Legend
        items={[
          { label: "Noodler Current", color: "var(--hmi-c3)" },
          { label: "Conveyor Current", color: "var(--hmi-c4)" },
          { label: "TRM Current", color: "var(--hmi-c5)" },
        ]}
      />
      <div className="hmi-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="rgba(140,170,210,0.10)" vertical={false} />
            <XAxis dataKey="t" stroke={AXIS.stroke} tick={AXIS.tick} minTickGap={40} tickLine={false} />
            <YAxis stroke={AXIS.stroke} tick={AXIS.tick} tickLine={false} width={44} domain={["auto", "auto"]} />
            <Tooltip content={<HmiTooltip unit=" A" />} cursor={{ stroke: "rgba(255,255,255,0.18)" }} />
            <Line type="monotone" dataKey="noodler" name="Noodler Current" stroke="var(--hmi-c3)" strokeWidth={2.2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="conveyor" name="Conveyor Current" stroke="var(--hmi-c4)" strokeWidth={2.2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="trm" name="TRM Current" stroke="var(--hmi-c5)" strokeWidth={2.2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}
