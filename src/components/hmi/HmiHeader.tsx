import { useEffect, useState } from "react";
import { StatusPill } from "./primitives";

export function HmiHeader({ fault }: { fault: boolean }) {
  const [time, setTime] = useState("--:--:--");

  useEffect(() => {
    const update = () => setTime(new Date().toLocaleTimeString([], { hour12: false }));
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="hmi-header hmi-area-head">
      <div className="hmi-brand">
        <div className="hmi-mark">C2</div>
        <div style={{ minWidth: 0 }}>
          <h1 className="hmi-title">CASCADE 2 · SOAP LINE</h1>
          <div className="hmi-subtitle">Data · Prediction · Estimation</div>
        </div>
      </div>
      <div className="hmi-header-right">
        <div className="hmi-meta">
          <span className="hmi-meta-label">Shift</span>
          <span className="hmi-meta-value">B · 08:00</span>
        </div>
        <div className="hmi-meta">
          <span className="hmi-meta-label">Line Time</span>
          <span className="hmi-meta-value">{time}</span>
        </div>
        <StatusPill tone={fault ? "warn" : "run"} label={fault ? "Attention" : "Line Running"} />
      </div>
    </header>
  );
}
