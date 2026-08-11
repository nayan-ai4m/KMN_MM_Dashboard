import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { HmiHeader } from "@/components/hmi/HmiHeader";
import { MixerSection } from "@/components/hmi/MixerSection";
import { TransportSection } from "@/components/hmi/TransportSection";
import { PrePlodderSection } from "@/components/hmi/PrePlodderSection";
import { FinalPlodderSection } from "@/components/hmi/FinalPlodderSection";
import { BsmSection } from "@/components/hmi/BsmSection";

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

function Dashboard() {
  const [batchType, setBatchType] = useState<"SOFT" | "HARD">("SOFT");

  useEffect(() => {
    const id = setInterval(() => {
      setBatchType((v) => (Math.random() < 0.06 ? (v === "SOFT" ? "HARD" : "SOFT") : v));
    }, 2000);
    return () => clearInterval(id);
  }, []);

  return (
    <main className="hmi-root">
      <HmiHeader />
      <MixerSection batchType={batchType} />
      <TransportSection />
      <PrePlodderSection />
      <FinalPlodderSection />
      <BsmSection />
    </main>
  );
}
