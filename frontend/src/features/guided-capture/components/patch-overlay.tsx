import { useHeldFace } from "@/features/guided-capture/hooks/use-held-face"
import { overlayPoints } from "@/features/guided-capture/lib/overlay-geometry"
import { PATCH_NAMES, type FrameMessage, type PatchName, type Point } from "@/lib/socket/messages"

const MIRRORED = true
const OUTLINE_GREEN = "#009e73"
const OUTLINE_EDGE = "#141414"
const LINE_WIDTH = 2
const EDGE_WIDTH = 5

type PatchOverlayProps = {
  scene: FrameMessage | null
}

type DrawnPatch = { name: PatchName; points: string }

function drawnPatches(scene: FrameMessage | null): DrawnPatch[] {
  if (scene === null) {
    return []
  }
  return PATCH_NAMES.flatMap((name) => {
    const outline: Point[] | null = scene.patches[name].outline
    return outline === null ? [] : [{ name, points: overlayPoints(outline, MIRRORED) }]
  })
}

export function PatchOverlay({ scene }: PatchOverlayProps) {
  const patches = drawnPatches(useHeldFace(scene))
  return (
    <svg
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
      className="pointer-events-none absolute inset-0 size-full"
    >
      {patches.map(({ name, points }) => (
        <polygon
          key={`edge-${name}`}
          points={points}
          fill="none"
          stroke={OUTLINE_EDGE}
          strokeWidth={EDGE_WIDTH}
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {patches.map(({ name, points }) => (
        <polygon
          key={`line-${name}`}
          data-testid={`patch-outline-${name}`}
          points={points}
          fill="none"
          stroke={OUTLINE_GREEN}
          strokeWidth={LINE_WIDTH}
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  )
}
