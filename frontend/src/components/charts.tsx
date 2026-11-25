"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Metrics } from "@/lib/types";

// Categorical slots validated with the dataviz palette checker (dark surface #141418):
// blue -> green -> violet -> orange passes CVD and normal-vision separation.
const SERIES = [
  { key: "awaiting_approval", label: "Awaiting approval", color: "#3987e5" },
  { key: "completed", label: "Completed", color: "#0ca30c" },
  { key: "failed", label: "Failed", color: "#9085e9" },
  { key: "rejected", label: "Rejected", color: "#d95926" },
] as const;

const tooltipStyle = {
  background: "#1b1b21",
  border: "1px solid #2b2b30",
  borderRadius: 6,
  fontSize: 12,
  color: "#f4f4f5",
};

export function WorkflowsPerDayChart({ data }: { data: Metrics["workflows_per_day"] }) {
  const rows = data.map((d) => ({ ...d, day: d.date.slice(5) }));
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, left: -16, bottom: 0 }} barCategoryGap="30%">
          <CartesianGrid vertical={false} stroke="#2b2b30" />
          <XAxis dataKey="day" tick={{ fill: "#a1a1aa", fontSize: 11 }} axisLine={{ stroke: "#2b2b30" }} tickLine={false} />
          <YAxis allowDecimals={false} tick={{ fill: "#a1a1aa", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(79,140,255,0.08)" }} />
          <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} iconType="circle" iconSize={8} />
          {SERIES.map((series) => (
            <Bar
              key={series.key}
              dataKey={series.key}
              name={series.label}
              stackId="outcome"
              fill={series.color}
              stroke="#141418"
              strokeWidth={2}
              radius={[3, 3, 0, 0]}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StateDistributionChart({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data)
    .filter(([, count]) => count > 0)
    .map(([state, count]) => ({ state: state.replace(/_/g, " "), count }))
    .sort((a, b) => b.count - a.count);
  if (rows.length === 0) return <p className="py-10 text-center text-sm text-muted">No workflows recorded yet.</p>;
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, left: 24, bottom: 0 }} barCategoryGap="25%">
          <CartesianGrid horizontal={false} stroke="#2b2b30" />
          <XAxis type="number" allowDecimals={false} tick={{ fill: "#a1a1aa", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="state" width={120} tick={{ fill: "#a1a1aa", fontSize: 11, fontFamily: "var(--font-mono)" }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(79,140,255,0.08)" }} />
          <Bar dataKey="count" name="Workflows" fill="#3987e5" radius={[0, 3, 3, 0]} isAnimationActive={false} label={{ position: "right", fill: "#a1a1aa", fontSize: 11 }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
