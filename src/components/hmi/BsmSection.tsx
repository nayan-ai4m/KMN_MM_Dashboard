import { Panel, StatusPill, type Tone } from "./primitives";
import { usePolledJson } from "@/lib/usePolledJson";

export type LaneRow = { lane: string; status: string; count: number };

function laneLabel(lane: string): string {
  const match = /^l(\d+)_/.exec(lane);
  return `Lane ${(match ? match[1] : lane).padStart(2, "0")}`;
}

function laneTone(status: string): Tone {
  return status.toLowerCase() === "running" ? "run" : "fault";
}

const OVERALL_BY_RUNNING: Record<number, { tone: Tone; label: string }> = {
  0: { tone: "fault", label: "STOPPED" },
  1: { tone: "warn", label: "SLO Mode" },
  2: { tone: "warn", label: "DLO Mode" },
  3: { tone: "run", label: "TLO Mode" },
  4: { tone: "run", label: "QLO Mode" },
};

export function BsmSection() {
  const lanes = usePolledJson<LaneRow[]>("/api/bsm/lanes", 10_000, []);
  const running = lanes.filter((l) => l.status.toLowerCase() === "running").length;
  const overall = lanes.length === 0 ? undefined : OVERALL_BY_RUNNING[running];

  return (
    <Panel
      area="hmi-area-bsm"
      title="BSM"
      sub="Binnachi · Lane status"
      right={
        <StatusPill
          tone={overall?.tone ?? "warn"}
          label={lanes.length === 0 ? "—" : (overall?.label ?? `${running}/${lanes.length} Running`)}
        />
      }
    >
      <div className="hmi-lanes">
        {lanes.map((lane) => (
          <div key={lane.lane} className={`hmi-lane is-${laneTone(lane.status)}`}>
            <span className="hmi-dot" />
            <div style={{ minWidth: 0, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span className="hmi-lane-name">{laneLabel(lane.lane)}</span>
              <span className="hmi-lane-count">{lane.count.toLocaleString()} soaps</span>
            </div>
            <div className="hmi-lane-state">{lane.status.toUpperCase()}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}
