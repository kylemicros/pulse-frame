import type { RefObject } from "react"

type RunCameraProps = {
  videoRef: RefObject<HTMLVideoElement | null>
  live: boolean
  offText: string | null
  cue: string | null
}

export function RunCamera({ videoRef, live, offText, cue }: RunCameraProps) {
  return (
    <div className="relative aspect-4/3 w-full overflow-hidden rounded-lg border border-(--ds-border) bg-(--ds-cam-bg)">
      <video
        ref={videoRef}
        aria-label="Camera preview"
        className={live ? "size-full -scale-x-100 object-cover" : "invisible size-full"}
        autoPlay
        muted
        playsInline
      />
      <svg
        viewBox="0 0 200 150"
        aria-hidden="true"
        focusable="false"
        className="pointer-events-none absolute inset-0 size-full fill-none stroke-(--ds-edge) stroke-2 [stroke-dasharray:6_6]"
      >
        <ellipse cx="100" cy="64" rx="30" ry="38" vectorEffect="non-scaling-stroke" />
        <path d="M40 150 C 45 114, 75 106, 100 106 C 125 106, 155 114, 160 150" vectorEffect="non-scaling-stroke" />
      </svg>
      {offText === null ? null : (
        <p className="pointer-events-none absolute inset-x-3 top-3 text-sm text-(--ds-cam-text)">{offText}</p>
      )}
      {cue === null ? null : (
        <p className="absolute inset-x-3 bottom-3 rounded-md border border-(--ds-edge) bg-(--ds-surface) px-3 py-2 text-[0.9375rem] text-(--ds-text)">
          {cue}
        </p>
      )}
    </div>
  )
}
