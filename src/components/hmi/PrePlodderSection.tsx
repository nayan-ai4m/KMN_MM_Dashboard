import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS, HmiTooltip, KpiTile, Legend, Panel, StatusPill } from "./primitives";
import type { Point } from "@/lib/hmi-mock";
import { usePolledJson } from "@/lib/usePolledJson";

type PrePlodderStatus = { rpm: number | null; turboInletTemp: number | null; running: boolean };

export function PrePlodderSection() {
  const data = usePolledJson<Point[]>("/api/pre-plodder/recent?minutes=10", 10_000, []);
  const status = usePolledJson<PrePlodderStatus>("/api/pre-plodder/status", 10_000, {
    rpm: null,
    turboInletTemp: null,
    running: false,
  });

  return (
    <Panel
      area="hmi-area-pre"
      title="Pre-Plodder"
      sub="Data"
      right={<StatusPill tone={status.running ? "run" : "fault"} label={status.running ? "Running" : "Stopped"} />}
    >
      <Legend items={[{ label: "Pre-Plodder Current", color: "var(--hmi-c1)" }]} />
      <div className="hmi-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="rgba(140,170,210,0.10)" vertical={false} />
            <XAxis dataKey="t" stroke={AXIS.stroke} tick={AXIS.tick} minTickGap={44} tickLine={false} />
            <YAxis stroke={AXIS.stroke} tick={AXIS.tick} tickLine={false} width={44} domain={["auto", "auto"]} />
            <Tooltip content={<HmiTooltip unit=" A" />} cursor={{ stroke: "rgba(255,255,255,0.18)" }} />
            <Line type="monotone" dataKey="current" name="Current" stroke="var(--hmi-c1)" strokeWidth={2.4} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="hmi-tiles">
        <KpiTile label="RPM" value={status.rpm != null ? status.rpm.toFixed(0) : "—"} />
        <KpiTile
          label="Turbo Inlet Temp"
          value={status.turboInletTemp != null ? status.turboInletTemp.toFixed(1) : "—"}
          unit="°C"
          tone={status.turboInletTemp != null && status.turboInletTemp > 46 ? "warn" : "idle"}
        />
        <KpiTile label="Running Status" value={status.running ? "RUNNING" : "STOPPED"} tone={status.running ? "run" : "fault"} />
      </div>
    </Panel>
  );
}
