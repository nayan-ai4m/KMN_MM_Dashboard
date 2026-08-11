import { Panel, StatusPill, type Tone } from "./primitives";

export type LaneState = "ACTIVE" | "BLOCKED" | "IDLE";

const TONE: Record<LaneState, Tone> = { ACTIVE: "run", BLOCKED: "fault", IDLE: "warn" };

export function BsmSection({ lanes }: { lanes: { name: string; state: LaneState; count: number }[] }) {
  const blocked = lanes.some((l) => l.state === "BLOCKED");
  const overall: Tone = blocked ? "fault" : lanes.every((l) => l.state === "ACTIVE") ? "run" : "warn";

  return (
    <Panel
      area="hmi-area-bsm"
      title="BSM"
      sub="End of line · Lane status"
      right={<StatusPill tone={overall} label={blocked ? "Lane Blocked" : overall === "run" ? "All Active" : "Partial"} />}
    >
      <div className="hmi-lanes">
        {lanes.map((lane) => (
          <div key={lane.name} className={`hmi-lane is-${TONE[lane.state]}`}>
            <span className="hmi-dot" />
            <div style={{ minWidth: 0 }}>
              <div className="hmi-lane-name">{lane.name}</div>
              <div className="hmi-lane-count">{lane.count.toLocaleString()} bars</div>
            </div>
            <div className="hmi-lane-state">{lane.state}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}
