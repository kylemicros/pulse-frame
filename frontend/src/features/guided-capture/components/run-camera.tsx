import { useState, type RefObject, type SyntheticEvent } from "react"
import { FRAME_HEIGHT, FRAME_WIDTH } from "@/features/capture"
import { PatchOverlay } from "@/features/guided-capture/components/patch-overlay"
import { PrivacyLock } from "@/features/guided-capture/components/privacy-lock"
import type { FrameMessage } from "@/lib/socket/messages"

type RunCameraProps = {
  videoRef: RefObject<HTMLVideoElement | null>
  live: boolean
  shown: boolean
  scene: FrameMessage | null
  offText: string | null
  hiddenLabel: string | null
  cue: string | null
  setupCue: string | null
  outlineOn: boolean
}

type SourceSize = { width: number; height: number }

const PLANNED_SIZE: SourceSize = { width: FRAME_WIDTH, height: FRAME_HEIGHT }

export function RunCamera({
  videoRef,
  live,
  shown,
  scene,
  offText,
  hiddenLabel,
  cue,
  setupCue,
  outlineOn,
}: RunCameraProps) {
  const [source, setSource] = useState(PLANNED_SIZE)
  const readSize = (event: SyntheticEvent<HTMLVideoElement>) => {
    const { videoWidth, videoHeight } = event.currentTarget
    if (videoWidth > 0 && videoHeight > 0) {
      setSource({ width: videoWidth, height: videoHeight })
    }
  }
  return (
    <div className="flex min-w-0 flex-col gap-3 lg:h-full lg:w-[min(100cqw,calc(100cqh*16/9))]">
      <div className="relative aspect-4/3 max-h-[60dvh] w-full overflow-hidden rounded-lg border border-(--ds-border) bg-(--ds-cam-bg) lg:aspect-auto lg:max-h-none lg:min-h-0 lg:flex-1">
        <video
          ref={videoRef}
          aria-label="Camera preview"
          className={live ? "size-full -scale-x-100 object-cover" : "invisible size-full"}
          onLoadedMetadata={readSize}
          onResize={readSize}
          autoPlay
          muted
          playsInline
        />
        <svg
          viewBox="0 0 200 150"
          preserveAspectRatio="xMidYMid slice"
          aria-hidden="true"
          focusable="false"
          className="pointer-events-none absolute inset-0 size-full fill-none stroke-(--ds-edge) stroke-2 [stroke-dasharray:6_6]"
        >
          <ellipse cx="100" cy="64" rx="30" ry="38" vectorEffect="non-scaling-stroke" />
          <path d="M40 150 C 45 114, 75 106, 100 106 C 125 106, 155 114, 160 150" vectorEffect="non-scaling-stroke" />
        </svg>
        {live && outlineOn ? (
          <PatchOverlay scene={scene} sourceWidth={source.width} sourceHeight={source.height} />
        ) : null}
        {offText === null ? null : (
          <p className="pointer-events-none absolute inset-x-4 top-16.5 text-sm text-(--ds-cam-text)">{offText}</p>
        )}
        {hiddenLabel === null ? null : <p className="sr-only">{hiddenLabel}</p>}
        {setupCue === null ? null : (
          <p
            aria-hidden="true"
            className="absolute inset-x-3 bottom-3 rounded-md border border-l-4 border-(--ds-edge) border-l-(--ds-count) bg-(--ds-surface) px-3 py-2 text-lg font-bold text-(--ds-text)"
          >
            {setupCue}
          </p>
        )}
        {cue === null ? null : (
          <p className="absolute inset-x-3 bottom-3 rounded-md border border-(--ds-edge) bg-(--ds-surface) px-3 py-2 text-[0.9375rem] text-(--ds-text)">
            {cue}
          </p>
        )}
        <PrivacyLock shown={shown} />
      </div>
    </div>
  )
}
