import { RunBar } from "@/features/guided-capture/components/run-bar"
import { LIVE_WINDOW_TEXT } from "@/features/guided-capture/lib/run-copy"
import { ACQUIRE_MS, settlingSeconds } from "@/features/guided-capture/lib/reading-copy"
import type { MonitorState } from "@/features/guided-capture/types"

type LiveHeartRateProps = {
  monitor: MonitorState
  lastGoodBpm: number | null
}

function settlePercent(monitor: MonitorState): number {
  const { reading, acquiringSince, latestT } = monitor
  if (reading?.state !== "acquiring") {
    return 0
  }
  const total = ACQUIRE_MS / 1000
  const left = settlingSeconds(acquiringSince ?? reading.t, latestT)
  return Math.round(((total - left) / total) * 100)
}

export function LiveHeartRate({ monitor, lastGoodBpm }: LiveHeartRateProps) {
  const { reading } = monitor
  const liveBpm = reading?.state === "ok" ? reading.bpm : null
  const shown = liveBpm ?? lastGoodBpm
  if (shown !== null) {
    const held = liveBpm === null
    return (
      <div>
        <dt className="text-sm font-semibold">Heart rate</dt>
        <dd>
          <span
            className={
              held
                ? "font-mono text-[1.75rem] leading-tight font-bold text-(--ds-muted) tabular-nums"
                : "font-mono text-[1.75rem] leading-tight font-bold tabular-nums"
            }
          >
            {Math.round(shown)}
          </span>
          <abbr title="beats per minute" className="ml-1.5 font-mono text-sm font-bold text-(--ds-muted) no-underline">
            BPM
          </abbr>
          {held ? <span className="ml-1.5 text-sm font-semibold text-(--ds-muted)">Last good</span> : null}
        </dd>
        <dd className="text-sm text-(--ds-muted)">{LIVE_WINDOW_TEXT}</dd>
      </div>
    )
  }
  if (reading?.state === "low_quality") {
    return (
      <div>
        <dt className="text-sm font-semibold">Heart rate</dt>
        <dd className="font-bold">No reading yet</dd>
        <dd className="text-sm text-(--ds-muted)">{LIVE_WINDOW_TEXT}</dd>
      </div>
    )
  }
  const percent = settlePercent(monitor)
  return (
    <div>
      <dt className="text-sm font-semibold">Heart rate</dt>
      <dd className="font-bold">{`Settling, ${percent}%`}</dd>
      <dd className="mt-1">
        <RunBar
          label="Heart rate settling"
          percent={percent}
          valueText={`Settling ${percent} percent`}
          fillClassName="bg-(--ds-muted)"
          thin
        />
      </dd>
      <dd className="text-sm text-(--ds-muted)">{`${LIVE_WINDOW_TEXT}, once settled`}</dd>
    </div>
  )
}
