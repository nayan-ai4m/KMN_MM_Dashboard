import { useCallback, useMemo } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS, HmiTooltip, Legend, Panel, StatusPill } from "./primitives";
import { drift, nowLabel, transportSeries, useLiveSeries, type Point } from "@/lib/hmi-mock";

export function TransportSection() {
  const initial = useMemo(() => transportSeries(), []);
  const next = useCallback(
    (prev: Point): Point => ({
      t: nowLabel(),
      noodler: drift(Number(prev["noodler"]), 4, 28, 50),
      conveyor: drift(Number(prev["conveyor"]), 2, 10, 24),
      trm: drift(Number(prev["trm"]), 3.5, 18, 38),
    }),
    [],
  );
  const data = useLiveSeries(initial, next);

  return (
    <Panel
      area="hmi-area-transport"
      title="Transport"
      sub="Noodler · Conveyor · TRM"
      right={<StatusPill tone="run" label="Flow OK" />}
    >
      <Legend
        items={[
          { label: "Noodler", color: "var(--hmi-c3)" },
          { label: "Conveyor", color: "var(--hmi-c4)" },
          { label: "TRM", color: "var(--hmi-c5)" },
        ]}
      />
      <div className="hmi-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="rgba(140,170,210,0.10)" vertical={false} />
            <XAxis dataKey="t" stroke={AXIS.stroke} tick={AXIS.tick} minTickGap={40} tickLine={false} />
            <YAxis stroke={AXIS.stroke} tick={AXIS.tick} tickLine={false} width={44} domain={[0, 55]} />
            <Tooltip content={<HmiTooltip unit=" A" />} cursor={{ stroke: "rgba(255,255,255,0.18)" }} />
            <Line type="monotone" dataKey="noodler" name="Noodler" stroke="var(--hmi-c3)" strokeWidth={2.2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="conveyor" name="Conveyor" stroke="var(--hmi-c4)" strokeWidth={2.2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="trm" name="TRM" stroke="var(--hmi-c5)" strokeWidth={2.2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}
