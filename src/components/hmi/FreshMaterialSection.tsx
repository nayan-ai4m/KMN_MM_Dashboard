import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip } from "recharts";
import { Panel, TrendArrow, hardnessColor } from "./primitives";
import { usePolledJson } from "@/lib/usePolledJson";

type BatchShare = { batch: string; percent: number };

type FreshMaterialPoint = {
  startTime: string | null;
  endTime: string | null;
  durRan: number | null;
  kgAdded: number | null;
  hardness: number | null;
  batches: BatchShare[];
};

type TrendMetric = "durRan" | "kgAdded" | "hardness";

type TrendConfig = {
  key: TrendMetric;
  label: string;
  unit?: string;
  color: string;
  decimals: number;
};

const TRENDS: TrendConfig[] = [
  { key: "durRan", label: "Noodler Duration", unit: "s", color: "var(--hmi-c1)", decimals: 0 },
  { key: "hardness", label: "New Material Hardness", color: "var(--hmi-c6)", decimals: 2 },
];

// Colors for batch composition segments, assigned in first-seen order across
// the visible window. Kept distinct from the accent colors the other rows
// in this panel already use (c1, c3) so a batch split never reads as one of them.
const BATCH_COLORS = ["var(--hmi-c2)"];

function buildBatchColorMap(data: FreshMaterialPoint[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const point of data) {
    for (const { batch } of point.batches) {
      if (!map.has(batch)) {
        map.set(batch, BATCH_COLORS[map.size % BATCH_COLORS.length]);
      }
    }
  }
  return map;
}

type BarDatum = { i: number; value: number; startTime: string | null; endTime: string | null };

function TrendTooltip({
  active,
  payload,
  config,
}: {
  active?: boolean;
  payload?: { payload: BarDatum }[];
  config: TrendConfig;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="hmi-tooltip">
      <div className="hmi-tooltip-label">{d.startTime && d.endTime ? `${d.startTime} to ${d.endTime}` : "—"}</div>
      <div style={{ color: config.color }}>
        {config.label}: {d.value.toFixed(config.decimals)}
        {config.unit ?? ""}
      </div>
    </div>
  );
}

function TrendRow({ config, data }: { config: TrendConfig; data: FreshMaterialPoint[] }) {
  const bars: BarDatum[] = data.map((d, i) => ({
    i,
    value: d[config.key] ?? 0,
    startTime: d.startTime,
    endTime: d.endTime,
  }));
  const latestPoint = data.length > 0 ? data[data.length - 1] : null;
  const latest = latestPoint ? latestPoint[config.key] : null;
  const previousPoint = data.length > 1 ? data[data.length - 2] : null;
  const previous = previousPoint ? previousPoint[config.key] : null;

  const isHardness = config.key === "hardness";
  const valueColor = isHardness && latest != null ? hardnessColor(latest) : undefined;
  const trend = isHardness && latest != null && previous != null && latest !== previous
    ? latest > previous
      ? { direction: "up" as const, color: "var(--hmi-fault)" }
      : { direction: "down" as const, color: "var(--hmi-run)" }
    : null;

  return (
    <div className="hmi-trend-row">
      <div className="hmi-trend-value">
        <div className="hmi-tile-label">{config.label}</div>
        <div className="hmi-tile-value" style={valueColor ? { color: valueColor } : undefined}>
          {latest != null ? latest.toFixed(config.decimals) : "—"}
          {config.unit ? <span className="hmi-tile-unit">{config.unit}</span> : null}
          {trend ? <TrendArrow direction={trend.direction} color={trend.color} /> : null}
        </div>
        {/* {config.key === "durRan" && latestPoint?.startTime && latestPoint?.endTime ? (
          <div className="hmi-trend-range">
            {latestPoint.startTime} to {latestPoint.endTime}
          </div>
        ) : null} */}
      </div>
      <div className="hmi-trend-chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bars} margin={{ top: 16, right: 4, bottom: 0, left: 4 }}>
            <Tooltip content={<TrendTooltip config={config} />} cursor={{ fill: "rgba(255,255,255,0.06)" }} />
            <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              <LabelList
                dataKey="value"
                position="top"
                formatter={(v: number) => v.toFixed(config.decimals)}
                fill="var(--hmi-text)"
                fontSize={10}
              />
              {bars.map((b) => (
                <Cell
                  key={b.i}
                  fill={isHardness ? hardnessColor(b.value) : config.color}
                  opacity={b.i === bars.length - 1 ? 1 : 0.45}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

type MaterialBarDatum = {
  i: number;
  startTime: string | null;
  endTime: string | null;
  totalKg: number;
  seg0Value: number;
  seg0Batch: string | null;
  seg0Percent: number | null;
  seg1Value: number;
  seg1Batch: string | null;
  seg1Percent: number | null;
};

function buildMaterialBars(data: FreshMaterialPoint[]): MaterialBarDatum[] {
  return data.map((d, i) => {
    const kgAdded = d.kgAdded ?? 0;
    const sorted = [...d.batches].sort((a, b) => b.percent - a.percent);
    const [first, second] = sorted;
    return {
      i,
      startTime: d.startTime,
      endTime: d.endTime,
      totalKg: kgAdded,
      seg0Value: first ? (first.percent / 100) * kgAdded : kgAdded,
      seg0Batch: first?.batch ?? null,
      seg0Percent: first?.percent ?? null,
      seg1Value: second ? (second.percent / 100) * kgAdded : 0,
      seg1Batch: second?.batch ?? null,
      seg1Percent: second?.percent ?? null,
    };
  });
}

function segmentLabelRenderer(bars: MaterialBarDatum[], pick: (b: MaterialBarDatum) => [string | null, number | null]) {
  return (props: {
    x?: string | number;
    y?: string | number;
    width?: string | number;
    height?: string | number;
    index?: number;
  }) => {
    const { index } = props;
    const x = Number(props.x);
    const y = Number(props.y);
    const width = Number(props.width);
    const height = Number(props.height);
    if (index == null || [x, y, width, height].some((n) => Number.isNaN(n))) return null;
    const [batch, percent] = pick(bars[index]);
    if (batch == null || percent == null || height < 12) return null;
    return (
      <text
        x={x + width / 2}
        y={y + height / 2}
        textAnchor="middle"
        dominantBaseline="central"
        fill="var(--hmi-text)"
        fontSize={9}
      >
        {`B${batch}`}
      </text>
    );
  };
}

function dividerRenderer(bars: MaterialBarDatum[]) {
  return (props: { x?: string | number; y?: string | number; width?: string | number; index?: number }) => {
    const { index } = props;
    const x = Number(props.x);
    const y = Number(props.y);
    const width = Number(props.width);
    if (index == null || [x, y, width].some((n) => Number.isNaN(n))) return null;
    if (!bars[index].seg1Batch) return null;
    return <rect x={x} y={y - 1} width={width} height={2} fill="var(--hmi-tile)" />;
  };
}

function MaterialAddedTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: MaterialBarDatum }[];
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const segments = [
    { batch: d.seg0Batch, percent: d.seg0Percent, value: d.seg0Value },
    { batch: d.seg1Batch, percent: d.seg1Percent, value: d.seg1Value },
  ].filter((s): s is { batch: string; percent: number; value: number } => s.batch != null);

  return (
    <div className="hmi-tooltip">
      <div className="hmi-tooltip-label">{d.startTime && d.endTime ? `${d.startTime} to ${d.endTime}` : "—"}</div>
      <div style={{ color: "var(--hmi-c2)" }}>New Material Added: {d.totalKg.toFixed(1)}kg</div>
      {segments.map((s) => (
        <div key={s.batch}>
          Batch {s.batch}: {s.percent.toFixed(0)}%
        </div>
      ))}
    </div>
  );
}

function MaterialAddedRow({ data }: { data: FreshMaterialPoint[] }) {
  const colorMap = buildBatchColorMap(data);
  const bars = buildMaterialBars(data);
  const latestPoint = data.length > 0 ? data[data.length - 1] : null;

  return (
    <div className="hmi-trend-row">
      <div className="hmi-trend-value">
        <div className="hmi-tile-label">New Material Added</div>
        <div className="hmi-tile-value">
          {latestPoint?.kgAdded != null ? latestPoint.kgAdded.toFixed(1) : "—"}
          <span className="hmi-tile-unit">kg</span>
        </div>
      </div>
      <div className="hmi-trend-chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bars} margin={{ top: 16, right: 4, bottom: 0, left: 4 }}>
            <Tooltip content={<MaterialAddedTooltip />} cursor={{ fill: "rgba(255,255,255,0.06)" }} />
            <Bar dataKey="seg0Value" stackId="batch" isAnimationActive={false}>
              <LabelList dataKey="seg0Value" content={segmentLabelRenderer(bars, (b) => [b.seg0Batch, b.seg0Percent])} />
              <LabelList dataKey="seg0Value" content={dividerRenderer(bars)} />
              {bars.map((b) => (
                <Cell
                  key={b.i}
                  fill={b.seg0Batch ? colorMap.get(b.seg0Batch) : "var(--hmi-c2)"}
                  opacity={b.i === bars.length - 1 ? 1 : 0.45}
                  radius={(b.seg1Batch ? undefined : [3, 3, 0, 0]) as unknown as number}
                />
              ))}
            </Bar>
            <Bar dataKey="seg1Value" stackId="batch" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              <LabelList
                dataKey="totalKg"
                position="top"
                formatter={(v: number) => v.toFixed(1)}
                fill="var(--hmi-text)"
                fontSize={10}
              />
              <LabelList dataKey="seg1Value" content={segmentLabelRenderer(bars, (b) => [b.seg1Batch, b.seg1Percent])} />
              {bars.map((b) => (
                <Cell
                  key={b.i}
                  fill={b.seg1Batch ? colorMap.get(b.seg1Batch) : "transparent"}
                  opacity={b.i === bars.length - 1 ? 1 : 0.45}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function FreshMaterialSection() {
  const data = usePolledJson<FreshMaterialPoint[]>("/api/fresh-material/recent?limit=10", 10_000, []);
  const latestPoint = data.length > 0 ? data[data.length - 1] : null;

  return (
    <Panel
      area="hmi-area-fresh"
      title="New Material "
      sub="last 10 cycles"
      right={
        latestPoint?.startTime && latestPoint?.endTime ? (
          <span className="hmi-donut-latest">
            Latest · {latestPoint.startTime} to {latestPoint.endTime}
          </span>
        ) : undefined
      }
    >
      <TrendRow config={TRENDS[0]} data={data} />
      <MaterialAddedRow data={data} />
      <TrendRow config={TRENDS[1]} data={data} />
    </Panel>
  );
}
