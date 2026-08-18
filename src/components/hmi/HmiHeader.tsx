import { useEffect, useState } from "react";
import { StatusPill, type Tone } from "./primitives";
import type { LaneRow } from "./BsmSection";
import { SkuConfigModal } from "./SkuConfigModal";
import { usePolledJson } from "@/lib/usePolledJson";

function shiftForHour(hour: number): "A" | "B" | "C" {
  if (hour >= 7 && hour < 15) return "A";
  if (hour >= 15 && hour < 23) return "B";
  return "C";
}

export function HmiHeader() {
  const [time, setTime] = useState("--:--:--");
  const [shift, setShift] = useState<"A" | "B" | "C">(() => shiftForHour(new Date().getHours()));
  const [skuModalOpen, setSkuModalOpen] = useState(false);
  const lanes = usePolledJson<LaneRow[]>("/api/bsm/lanes", 10_000, []);

  useEffect(() => {
    const update = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString([], { hour12: false }));
      setShift(shiftForHour(now.getHours()));
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, []);

  const runningLanes = lanes.filter((l) => l.status.toLowerCase() === "running").length;
  const lineTone: Tone = runningLanes === 0 ? "fault" : runningLanes <= 2 ? "warn" : "run";
  const lineLabel = lanes.length === 0 ? "—" : runningLanes === 0 ? "Line Stopped" : "Line Running";

  return (
    <header className="hmi-header hmi-area-head">
      <div className="hmi-brand">
        <img src="ai4m_dark.png" alt="AI4M Logo" className="hmi-brand-logo" />
        <div style={{ minWidth: 0 }}>
          <h1 className="hmi-title">CASCADE 2 · SOAP LINE</h1>
          <div className="hmi-subtitle">Data · Prediction · Estimation</div>
        </div>
      </div>
      <div className="hmi-header-right">
        <div className="hmi-meta">
          <span className="hmi-meta-label">Shift</span>
          <span className="hmi-meta-value">{shift}</span>
        </div>
        <div className="hmi-meta">
          <span className="hmi-meta-label">Time</span>
          <span className="hmi-meta-value">{time}</span>
        </div>
        <button type="button" className="hmi-btn" onClick={() => setSkuModalOpen(true)}>
          SKU Config
        </button>
        <StatusPill tone={lanes.length === 0 ? "idle" : lineTone} label={lineLabel} />
      </div>
      {skuModalOpen ? <SkuConfigModal onClose={() => setSkuModalOpen(false)} /> : null}
    </header>
  );
}
