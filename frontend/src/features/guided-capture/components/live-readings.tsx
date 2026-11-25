import { useId } from "react"
import { LiveHeartRate } from "@/features/guided-capture/components/live-heart-rate"
import { QualityBadge } from "@/features/guided-capture/components/quality-badge"
import { VariationTiles } from "@/features/guided-capture/components/variation-tiles"
import { LIVE_WINDOW_TEXT, VARIATION_LATER } from "@/features/guided-capture/lib/run-copy"
import { qualityBand } from "@/features/guided-capture/lib/quality-band"
import type { MonitorState } from "@/features/guided-capture/types"

type LiveReadingsProps = {
  monitor: MonitorState
  lastGoodBpm: number | null
}

export function LiveReadings({ monitor, lastGoodBpm }: LiveReadingsProps) {
  const headingId = useId()
  const qualityDb = monitor.reading?.quality_db ?? null
  return (
    <section aria-labelledby={headingId} className="rounded-lg border border-(--ds-border) bg-(--ds-surface-2) p-3">
      <h3 id={headingId} className="mb-2 font-bold">
        Live readings
      </h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <LiveHeartRate monitor={monitor} lastGoodBpm={lastGoodBpm} />
        <div>
          <dt className="text-sm font-semibold">Signal quality</dt>
          <dd className={qualityDb === null ? "font-bold" : undefined}>
            {qualityDb === null ? "No value yet" : <QualityBadge band={qualityBand(qualityDb)} />}
          </dd>
          <dd className="text-sm text-(--ds-muted)">{LIVE_WINDOW_TEXT}</dd>
        </div>
        <VariationTiles tile="plain" />
      </dl>
      <p className="mt-2 text-sm text-(--ds-muted)">{VARIATION_LATER}</p>
    </section>
  )
}
