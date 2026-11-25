import type { HTMLAttributes } from "react";

import { cn, TONE_CLASSES } from "@/lib/utils";

export type Tone = "neutral" | "info" | "success" | "warning" | "serious" | "critical";

export function Badge({ tone = "neutral", className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-wide",
        TONE_CLASSES[tone],
        className,
      )}
      {...props}
    />
  );
}
