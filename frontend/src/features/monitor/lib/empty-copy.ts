import type { Phase } from "@/features/monitor/types"

export const NO_QUALITY_YET = "No value yet."

export const VIDEO_EMPTY: Record<Exclude<Phase, "running">, string> = {
  idle: "Camera's off. Press Start and your face shows up here.",
  starting: "Waking up the camera. Give it a second.",
}

export function pulseEmptyText(phase: Phase): string {
  return phase === "idle"
    ? "No pulse to draw yet. Press Start and the trace lands here."
    : "Listening for your pulse. The trace draws once there is enough of you to read."
}
