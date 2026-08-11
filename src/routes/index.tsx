import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { HmiHeader } from "@/components/hmi/HmiHeader";
import { MixerSection } from "@/components/hmi/MixerSection";
import { TransportSection } from "@/components/hmi/TransportSection";
import { PrePlodderSection } from "@/components/hmi/PrePlodderSection";
import { FinalPlodderSection } from "@/components/hmi/FinalPlodderSection";
import { BsmSection, type LaneState } from "@/components/hmi/BsmSection";

const TITLE = "Cascade 2 — Soap Line HMI Dashboard";
const DESC =
  "Live industrial HMI for the Cascade 2 soap production line: mixer batches, transport load, pre-plodder PV prediction, final plodder estimation and BSM lane status.";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: TITLE },
      { name: "description", content: DESC },
      { property: "og:title", content: TITLE },
      { property: "og:description", content: DESC },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Dashboard,
});

const LANE_NAMES = ["Lane 01", "Lane 02", "Lane 03", "Lane 04"];

function Dashboard() {
  const [batchCount, setBatchCount] = useState(148);
  const [batchType, setBatchType] = useState<"SOFT" | "HARD">("SOFT");
  const [rpm, setRpm] = useState(212);
  const [turboTemp, setTurboTemp] = useState(44.2);
  const [coneTemp, setConeTemp] = useState(71.6);
  const [running, setRunning] = useState(true);
  const [lanes, setLanes] = useState<{ name: string; state: LaneState; count: number }[]>(
    LANE_NAMES.map((name, i) => ({
      name,
      state: i === 2 ? "IDLE" : "ACTIVE",
      count: 1840 + i * 137,
    })),
  );

  useEffect(() => {
    const id = setInterval(() => {
      setRpm((v) => Math.round(Math.min(240, Math.max(180, v + (Math.random() - 0.5) * 8))));
      setTurboTemp((v) => +Math.min(52, Math.max(38, v + (Math.random() - 0.5) * 1.4)).toFixed(1));
      setConeTemp((v) => +Math.min(80, Math.max(64, v + (Math.random() - 0.5) * 1.2)).toFixed(1));
      setRunning((v) => (Math.random() < 0.03 ? !v : v));
      setBatchCount((v) => (Math.random() < 0.12 ? v + 1 : v));
      setBatchType((v) => (Math.random() < 0.06 ? (v === "SOFT" ? "HARD" : "SOFT") : v));
      setLanes((prev) =>
        prev.map((lane) => {
          const roll = Math.random();
          const state: LaneState =
            roll < 0.04 ? "BLOCKED" : roll < 0.12 ? "IDLE" : "ACTIVE";
          return {
            ...lane,
            state,
            count: lane.count + (state === "ACTIVE" ? Math.round(Math.random() * 12) : 0),
          };
        }),
      );
    }, 2000);
    return () => clearInterval(id);
  }, []);

  const fault = !running || lanes.some((l) => l.state === "BLOCKED");

  return (
    <main className="hmi-root">
      <HmiHeader fault={fault} />
      <MixerSection batchCount={batchCount} batchType={batchType} />
      <TransportSection />
      <PrePlodderSection rpm={rpm} turboTemp={turboTemp} running={running} />
      <FinalPlodderSection coneTemp={coneTemp} />
      <BsmSection lanes={lanes} />
    </main>
  );
}
