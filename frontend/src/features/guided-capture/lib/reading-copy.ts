import { countdownSeconds } from "@/features/guided-capture/lib/run-plan"
import type { FrameMessage } from "@/lib/socket/messages"

export const ACQUIRE_MS = 20000

export type SceneHint = "no-face" | "moving" | "steady"

export function sceneHint(scene: FrameMessage | null): SceneHint {
  if (scene === null || scene.face) {
    return scene?.moving === true ? "moving" : "steady"
  }
  return "no-face"
}

export const VIDEO_HINT: Record<SceneHint, string | null> = {
  "no-face": "No face found. Face the camera.",
  moving: "You're moving. Hold still.",
  steady: null,
}

export function settlingSeconds(since: number, latestT: number | null): number {
  return countdownSeconds(ACQUIRE_MS, latestT === null ? 0 : latestT - since)
}
