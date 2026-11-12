import type { FrameMessage } from "@/lib/socket/messages"

export const ACQUIRE_MS = 20000

export type SceneHint = "no-face" | "moving" | "steady"

export function sceneHint(scene: FrameMessage | null): SceneHint {
  if (scene === null || scene.face) {
    return scene?.moving === true ? "moving" : "steady"
  }
  return "no-face"
}

export const DASH_REASON: Record<SceneHint, string> = {
  "no-face": "No face in view. Sit where the camera can see you.",
  moving: "Hold still for a moment, the pulse hides when you move.",
  steady: "Can't find a pulse yet. More light helps: daylight beats a lamp.",
}

export const VIDEO_HINT: Record<SceneHint, string | null> = {
  "no-face": "No face found. Face the camera.",
  moving: "You're moving. Hold still.",
  steady: null,
}

export function settlingSeconds(since: number, latestT: number | null): number {
  const elapsed = latestT === null ? 0 : latestT - since
  const left = Math.ceil((ACQUIRE_MS - elapsed) / 1000)
  return Math.min(ACQUIRE_MS / 1000, Math.max(1, left))
}
