import { createFileRoute } from "@tanstack/react-router";
import { HmiHeader } from "@/components/hmi/HmiHeader";
import { MixerSection } from "@/components/hmi/MixerSection";
import { TransportSection } from "@/components/hmi/TransportSection";
import { PrePlodderSection } from "@/components/hmi/PrePlodderSection";
import { FinalPlodderSection } from "@/components/hmi/FinalPlodderSection";
import { RecycleSection } from "@/components/hmi/RecycleSection";
import { FreshMaterialSection } from "@/components/hmi/FreshMaterialSection";

const TITLE = "Cascade 2 — Soap Line HMI Dashboard";
const DESC =
  "Live industrial HMI for the Cascade 2 soap production line: mixer batches, transport load, pre-plodder PV prediction, final plodder estimation, fresh material feed and BSM lane status.";

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
  return (
    <main className="hmi-root">
      <HmiHeader />
      <MixerSection />
      <TransportSection />
      <RecycleSection />
      <PrePlodderSection />
      <FinalPlodderSection />
      <FreshMaterialSection />
    </main>
  );
}
