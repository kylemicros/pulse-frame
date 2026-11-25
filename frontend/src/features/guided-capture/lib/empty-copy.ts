import type { Phase } from "@/features/guided-capture/types"

export const VIDEO_EMPTY: Record<Exclude<Phase, "running">, string> = {
  idle: "Camera's off. Press Start and your face shows up here.",
  starting: "Waking up the camera. Give it a second.",
}
