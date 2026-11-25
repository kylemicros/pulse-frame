import { ResultHeartRate } from "@/features/guided-capture/components/result-heart-rate"
import { VariationTiles } from "@/features/guided-capture/components/variation-tiles"
import {
  NOT_ENOUGH_BEATS,
  NOT_ENOUGH_BEATS_DONE,
  VARIATION_LINE,
  VARIATION_WINDOW,
} from "@/features/guided-capture/lib/run-copy"
import type { RunResult } from "@/features/guided-capture/types"

const NO_VALUES = { "beat-to-beat": null, overall: null } as const

type RunResultsProps = {
  result: RunResult | null
}

function tileProps(result: RunResult | null) {
  if (result === null) {
    return { values: NO_VALUES, emptyText: NOT_ENOUGH_BEATS, windows: null }
  }
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
  return (
    <div className="flex flex-col gap-2">
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-(--ds-border) bg-(--ds-surface-2) px-4 py-3 sm:col-span-2">
          <dt className="font-semibold">Heart rate</dt>
          <ResultHeartRate result={result} />
        </div>
        <VariationTiles tile="boxed" {...tileProps(result)} />
      </dl>
      {result?.kind === "none" ? null : <p className="text-sm text-(--ds-muted)">{VARIATION_LINE}</p>}
    </div>
  )
}
