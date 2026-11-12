import type { RefObject } from "react"
import { Button } from "@/components/ui/button"
import { useHeldValue } from "@/features/monitor/hooks/use-held-value"
import { VIDEO_EMPTY } from "@/features/monitor/lib/empty-copy"
import { sceneHint, VIDEO_HINT } from "@/features/monitor/lib/reading-copy"
import { PatchOverlay } from "@/features/monitor/components/patch-overlay"
import type { Phase } from "@/features/monitor/types"
import type { FrameMessage } from "@/lib/socket/messages"

const MIRRORED = true

type CameraPanelProps = {
  videoRef: RefObject<HTMLVideoElement | null>
  phase: Phase
  scene: FrameMessage | null
  overlayOn: boolean
  onToggleOverlay: () => void
}

export function CameraPanel({ videoRef, phase, scene, overlayOn, onToggleOverlay }: CameraPanelProps) {
  const hint = VIDEO_HINT[useHeldValue(sceneHint(scene))]
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="relative aspect-4/3 w-full overflow-hidden bg-muted">
        <video
          ref={videoRef}
          aria-label="Camera preview"
          className="size-full -scale-x-100 object-cover"
          autoPlay
          muted
          playsInline
        />
        {overlayOn ? <PatchOverlay scene={scene} mirrored={MIRRORED} /> : null}
        {phase === "running" ? null : (
          <p
            data-testid="video-empty"
            className="pointer-events-none absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-muted-foreground"
          >
            {VIDEO_EMPTY[phase]}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1 text-sm">
          {hint === null ? null : <p className="font-medium text-foreground">{hint}</p>}
          <p className="text-muted-foreground">Glancing away resets the reading and the 20 s count starts over.</p>
        </div>
        <Button variant="outline" aria-pressed={overlayOn} onClick={onToggleOverlay}>
          Patch overlay
        </Button>
      </div>
    </div>
  )
}
