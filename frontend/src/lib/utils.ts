import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type { WorkflowState } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const HAPPY_PATH: WorkflowState[] = [
  "CREATED",
  "ANALYZING",
  "VERIFYING",
  "POLICY_CHECK",
  "AWAITING_APPROVAL",
  "APPROVED",
  "EXECUTING",
  "COMPLETED",
];

export const STATE_TONE: Record<WorkflowState, "neutral" | "info" | "success" | "warning" | "critical" | "serious"> = {
  CREATED: "neutral",
  ANALYZING: "info",
  VERIFYING: "info",
  POLICY_CHECK: "info",
  AWAITING_APPROVAL: "warning",
  APPROVED: "info",
  EXECUTING: "info",
  COMPLETED: "success",
  REJECTED: "critical",
  FAILED: "serious",
  CANCELLED: "neutral",
};

export const TONE_CLASSES: Record<string, string> = {
  neutral: "bg-border/60 text-muted border-border-strong",
  info: "bg-accent-soft text-accent border-accent/40",
  success: "bg-success/15 text-success border-success/40",
  warning: "bg-warning/15 text-warning border-warning/40",
  serious: "bg-serious/15 text-serious border-serious/40",
  critical: "bg-critical/15 text-critical border-critical/40",
};

export function hasPermission(permissions: string[] | undefined, permission: string): boolean {
  return Boolean(permissions?.includes(permission));
}
