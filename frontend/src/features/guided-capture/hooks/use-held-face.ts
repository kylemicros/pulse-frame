import { useState } from "react"
import { useHeldValue } from "@/features/guided-capture/hooks/use-held-value"
import type { FrameMessage } from "@/lib/socket/messages"

export function useHeldFace(scene: FrameMessage | null): FrameMessage | null {
  const found = scene !== null && scene.face
  const [lastFound, setLastFound] = useState<FrameMessage | null>(found ? scene : null)
  if (found && scene !== lastFound) {
    setLastFound(scene)
  }
  const held = useHeldValue(found ? "found" : "lost")
  if (scene === null || held === "lost") {
    return null
  }
  return found ? scene : lastFound
}
