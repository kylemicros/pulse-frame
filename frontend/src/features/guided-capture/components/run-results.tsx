import { ResultHeartRate } from "@/features/guided-capture/components/result-heart-rate"
import { VariationTiles } from "@/features/guided-capture/components/variation-tiles"
import { VARIATION_LATER } from "@/features/guided-capture/lib/run-copy"
import type { RunResult } from "@/features/guided-capture/types"

type RunResultsProps = {
  result: RunResult | null
}

export function RunResults({ result }: RunResultsProps) {
  return (
    <div className="flex flex-col gap-2">
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-(--ds-border) bg-(--ds-surface-2) px-4 py-3 sm:col-span-2">
          <dt className="font-semibold">Heart rate</dt>
          <ResultHeartRate result={result} />
        </div>
        <VariationTiles tile="boxed" />
      </dl>
      <p className="text-sm text-(--ds-muted)">{VARIATION_LATER}</p>
    </div>
  )
}
