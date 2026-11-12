import { overlayPoints } from "@/features/monitor/lib/overlay-geometry"
import { PATCH_NAMES, type FrameMessage, type PatchName } from "@/lib/socket/messages"

const PATCH_STROKE: Record<PatchName, string> = {
  forehead: "stroke-cyan-400",
  left_cheek: "stroke-amber-400",
  right_cheek: "stroke-fuchsia-400",
}

type PatchOverlayProps = {
  scene: FrameMessage | null
  mirrored: boolean
}

export function PatchOverlay({ scene, mirrored }: PatchOverlayProps) {
  const drawn = scene !== null && scene.face ? PATCH_NAMES : []
  return (
    <svg
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
      role="img"
      aria-label="Skin patch overlay"
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-0 size-full"
    >
      {drawn.map((name) => {
        const outline = scene?.patches[name].outline ?? null
        if (outline === null) {
          return null
        }
        return (
          <polygon
            key={name}
            data-testid={`patch-outline-${name}`}
            points={overlayPoints(outline, mirrored)}
            fill="none"
            strokeWidth={2}
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
            className={PATCH_STROKE[name]}
          />
        )
      })}
    </svg>
  )
}
