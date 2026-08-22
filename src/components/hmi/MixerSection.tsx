import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AXIS, HmiTooltip, Legend, Panel, StatusPill, TrendArrow, hardnessColor, hardnessLabel } from "./primitives";
import type { Point } from "@/lib/hmi-mock";
import { usePolledJson } from "@/lib/usePolledJson";

type MixerStatus = {
  batchCount: number | null;
  running: boolean;
  mixBatchNum: number | null;
  mixHardness: number | null;
  mixTime: string | null;
};

type MixerDropPoint = {
  time: string | null;
  batchNum: number | null;
  hardness: number | null;
  kgsDropped: number | null;
  dur: number | null;
  ageSeconds: number | null;
};

type DropBarDatum = {
  i: number;
  value: number;
  time: string | null;
  batchNum: number | null;
  kgsDropped: number | null;
  ageSeconds: number | null;
};

function formatAge(seconds: number | null): string {
  if (seconds == null) return "—";
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = Math.round(minutes % 60);
  return `${hours}h ${remMinutes}m`;
}

function DropTooltip({ active, payload }: { active?: boolean; payload?: { payload: DropBarDatum }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="hmi-tooltip">
      <div className="hmi-tooltip-label">
        {d.time ?? "—"} · Batch {d.batchNum ?? "—"}
      </div>
      <div style={{ color: hardnessColor(d.value) }}>Hardness: {d.value.toFixed(2)}</div>
      {/* <div>Dropped: {d.kgsDropped != null ? d.kgsDropped.toFixed(1) : "—"}kg</div> */}
      <div>Batch Age Time: {formatAge(d.ageSeconds)}</div>
    </div>
  );
}

export function MixerSection() {
  const status = usePolledJson<MixerStatus>("/api/mixer/status", 10_000, {
    batchCount: null,
    running: false,
    mixBatchNum: null,
    mixHardness: null,
    mixTime: null,
  });
  const drops = usePolledJson<MixerDropPoint[]>("/api/mixer/drops/recent?limit=10", 10_000, []);
  const currentData = usePolledJson<Point[]>("/api/mixer/recent?minutes=10", 10_000, []);

  const bars: DropBarDatum[] = drops.map((d, i) => ({
    i,
    value: d.hardness ?? 0,
    time: d.time,
    batchNum: d.batchNum,
    kgsDropped: d.kgsDropped,
    ageSeconds: d.ageSeconds,
  }));
  const latestPoint = drops.length > 0 ? drops[drops.length - 1] : null;
  const latestHardness = latestPoint?.hardness ?? null;
  const previousPoint = drops.length > 1 ? drops[drops.length - 2] : null;
  const previousHardness = previousPoint?.hardness ?? null;
  const trend =
    latestHardness != null && previousHardness != null && latestHardness !== previousHardness
      ? latestHardness > previousHardness
        ? { direction: "up" as const, color: "var(--hmi-fault)" }
        : { direction: "down" as const, color: "var(--hmi-run)" }
      : null;

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
        {status.mixHardness != null ? (
          <div style={{ textAlign: "right" }}>
            <div
              className="hmi-badge"
              style={{ color: hardnessColor(status.mixHardness) }}
              title={`Batch ${status.mixBatchNum ?? "—"} · currently mixing`}
            >
              <span className="hmi-dot" />
              {hardnessLabel(status.mixHardness)} - {status.mixHardness.toFixed(2)}
            </div>
            {/* {status.mixTime != null ? (
              <div className="hmi-donut-latest" style={{ marginTop: 4 }}>
                Started · {status.mixTime}
              </div>
            ) : null} */}
          </div>
        ) : null}
      </div>

      <div className="hmi-trend-row">
        <div className="hmi-trend-value">
          <div className="hmi-tile-label">
            Batch Hardness{latestPoint?.batchNum != null ? ` · #${latestPoint.batchNum}` : ""}
          </div>
          <div className="hmi-tile-value" style={latestHardness != null ? { color: hardnessColor(latestHardness) } : undefined}>
            {latestHardness != null ? latestHardness.toFixed(2) : "—"}
            {trend ? <TrendArrow direction={trend.direction} color={trend.color} /> : null}
          </div>
        </div>
        <div className="hmi-trend-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bars} margin={{ top: 16, right: 4, bottom: 0, left: 4 }}>
              <Tooltip content={<DropTooltip />} cursor={{ fill: "rgba(255,255,255,0.06)" }} />
              <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                <LabelList
                  dataKey="value"
                  position="top"
                  formatter={(v: number) => v.toFixed(2)}
                  fill="var(--hmi-text)"
                  fontSize={10}
                />
                {bars.map((b) => (
                  <Cell key={b.i} fill={hardnessColor(b.value)} opacity={b.i === bars.length - 1 ? 1 : 0.45} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
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
          <LineChart data={currentData} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
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
