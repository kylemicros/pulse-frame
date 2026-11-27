import { useId } from "react"
import { ResultHeartRate } from "@/features/guided-capture/components/result-heart-rate"
import { VariationTiles } from "@/features/guided-capture/components/variation-tiles"
import {
  CAMERA_OFF_DONE,
  NOT_ENOUGH_BEATS_DONE,
  VARIATION_LINE,
  VARIATION_WINDOW,
} from "@/features/guided-capture/lib/run-copy"
import type { RunResult } from "@/features/guided-capture/types"

const NO_VALUES = { "beat-to-beat": null, overall: null } as const

type RunResultsProps = {
  result: RunResult
}

function tileProps(result: RunResult) {
  if (result.kind === "none") {
    return { values: NO_VALUES, emptyText: NOT_ENOUGH_BEATS_DONE, windows: null }
  }
  return {
    values: { "beat-to-beat": result.beatToBeatMs, overall: result.overallMs },
    emptyText: NOT_ENOUGH_BEATS_DONE,
    windows: VARIATION_WINDOW.result,
  }
}

export function RunResults({ result }: RunResultsProps) {
  const headingId = useId()
  return (
    <section
      aria-labelledby={headingId}
      className="flex min-w-0 animate-phase-in flex-col gap-3.5 rounded-xl border border-(--ds-border) bg-(--ds-surface) p-5 shadow-[0_10px_30px_rgba(0,0,0,0.08)] motion-reduce:animate-none md:gap-5 md:px-10 md:py-8 lg:min-h-0 lg:overflow-y-auto"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={headingId} className="inline-flex items-center gap-2 text-base font-bold">
          <span aria-hidden="true" className="h-5 w-1.5 rounded-xs bg-(--ds-done)" />
          Result
        </h2>
        <span className="text-sm text-(--ds-muted)">{CAMERA_OFF_DONE}</span>
      </div>
      <div className="flex flex-col gap-3.5 md:gap-5 lg:my-auto">
        <dl>
          <div>
            <dt className="text-sm font-semibold">Heart rate</dt>
            <ResultHeartRate result={result} />
          </div>
        </dl>
        <dl className="grid grid-cols-2 gap-4">
          <VariationTiles tile="boxed" {...tileProps(result)} />
        </dl>
        {result.kind === "none" ? null : <p className="text-sm text-(--ds-muted)">{VARIATION_LINE}</p>}
      </div>
    </section>
  )
}
