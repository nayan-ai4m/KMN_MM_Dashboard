import { useCallback, useMemo } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS, HmiTooltip, KpiTile, Legend, Panel, StatusPill } from "./primitives";
import { drift, nowLabel, pvPredictionSeries, useLiveSeries, type Point } from "@/lib/hmi-mock";

export function PrePlodderSection({
  rpm,
  turboTemp,
  running,
}: {
  rpm: number;
  turboTemp: number;
  running: boolean;
}) {
  const initial = useMemo(() => pvPredictionSeries(), []);
  const next = useCallback((prev: Point): Point => {
    const base = Number(prev["predicted"] ?? prev["actual"] ?? 82);
    const actual = drift(base, 2.4, 74, 90);
    return { t: nowLabel(), actual, predicted: +(actual + (Math.random() - 0.4) * 1.6).toFixed(2) };
  }, []);
  const data = useLiveSeries(initial, next, 1800);
  const boundary = data[data.length - 12]?.["t"] as string | undefined;

  return (
    <Panel
      area="hmi-area-pre"
      title="Pre-Plodder"
      sub="Layer 02 · Prediction"
      right={<StatusPill tone={running ? "run" : "fault"} label={running ? "Running" : "Stopped"} />}
    >
      <Legend
        items={[
          { label: "PV Actual", color: "var(--hmi-c1)" },
          { label: "PV Predicted", color: "var(--hmi-c4)" },
        ]}
      />
      <div className="hmi-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="rgba(140,170,210,0.10)" vertical={false} />
            <XAxis dataKey="t" stroke={AXIS.stroke} tick={AXIS.tick} minTickGap={44} tickLine={false} />
            <YAxis stroke={AXIS.stroke} tick={AXIS.tick} tickLine={false} width={44} domain={[70, 95]} />
            <Tooltip content={<HmiTooltip unit=" PV" />} cursor={{ stroke: "rgba(255,255,255,0.18)" }} />
            {boundary ? (
              <ReferenceLine x={boundary} stroke="rgba(255,190,24,0.5)" strokeDasharray="4 4" />
            ) : null}
            <Line type="monotone" dataKey="actual" name="PV Actual" stroke="var(--hmi-c1)" strokeWidth={2.4} dot={false} connectNulls={false} isAnimationActive={false} />
            <Line
              type="monotone"
              dataKey="predicted"
              name="PV Predicted"
              stroke="var(--hmi-c4)"
              strokeWidth={2.4}
              strokeDasharray="5 4"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="hmi-tiles">
        <KpiTile label="RPM" value={rpm.toFixed(0)} />
        <KpiTile label="Turbo Inlet Temp" value={turboTemp.toFixed(1)} unit="°C" tone={turboTemp > 46 ? "warn" : "idle"} />
        <KpiTile label="Running Status" value={running ? "RUN" : "STOP"} tone={running ? "run" : "fault"} />
      </div>
    </Panel>
  );
}
