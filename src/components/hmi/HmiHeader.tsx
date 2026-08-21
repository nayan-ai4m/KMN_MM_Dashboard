import { useEffect, useState } from "react";
import { StatusPill, type Tone } from "./primitives";
import { SkuConfigModal, type SkuConfig } from "./SkuConfigModal";
import { usePolledJson } from "@/lib/usePolledJson";

export type LaneRow = { lane: string; status: string; count: number };

function shiftForHour(hour: number): "A" | "B" | "C" {
  if (hour >= 7 && hour < 15) return "A";
  if (hour >= 15 && hour < 23) return "B";
  return "C";
}

function laneLabel(lane: string): string {
  const match = /^l(\d+)_/.exec(lane);
  return `Lane ${match ? Number(match[1]) : lane}`;
}

function laneTone(status: string): Tone {
  return status.toLowerCase() === "running" ? "run" : "fault";
}

export function HmiHeader() {
  const [time, setTime] = useState("--:--:--");
  const [shift, setShift] = useState<"A" | "B" | "C">(() => shiftForHour(new Date().getHours()));
  const [skuModalOpen, setSkuModalOpen] = useState(false);
  const lanes = usePolledJson<LaneRow[]>("/api/bsm/lanes", 10_000, []);
  const skuConfig = usePolledJson<SkuConfig>("/api/sku-config", 30_000, { activeSku: null, skus: [] });
  const activeSku = skuConfig.skus.find((s) => s.skuCode === skuConfig.activeSku) ?? null;

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

  return (
    <header className="hmi-header hmi-area-head">
      <div className="hmi-brand">
        <img src="ai4m_dark.png" alt="AI4M Logo" className="hmi-brand-logo" />
        <div style={{ minWidth: 0 }}>
          <h1 className="hmi-title">CASCADE 2 · SOAP LINE</h1>
          <div className="hmi-subtitle">Data · Prediction · Estimation</div>
        </div>
      </div>
      <div className="hmi-lane-pills">
        {lanes.length === 0 ? (
          <StatusPill tone="idle" label="—" />
        ) : (
          lanes.map((lane) => <StatusPill key={lane.lane} tone={laneTone(lane.status)} label={laneLabel(lane.lane)} />)
        )}
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
        <div className="hmi-meta">
          <span className="hmi-meta-label">Active SKU</span>
          <span className="hmi-meta-value">
            {activeSku ? `${activeSku.skuCode}` : "—"}
          </span>
        </div>
        <button type="button" className="hmi-btn" onClick={() => setSkuModalOpen(true)}>
          SKU Config
        </button>
      </div>
      {skuModalOpen ? <SkuConfigModal onClose={() => setSkuModalOpen(false)} /> : null}
    </header>
  );
}
