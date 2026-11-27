import { averageLine } from "@/features/guided-capture/lib/run-copy"
import type { RunResult } from "@/features/guided-capture/types"

type ResultHeartRateProps = {
  result: RunResult
}

export function ResultHeartRate({ result }: ResultHeartRateProps) {
  if (result.kind === "none") {
    return (
      <>
        <dd className="mt-1 text-[2rem] leading-[1.2] font-bold">No reading this time</dd>
        <dd className="text-sm text-(--ds-muted)">Last counted minute.</dd>
      </>
    )
  }
  return (
    <>
      <dd className="flex flex-wrap items-baseline gap-x-3.5">
        <span className="font-mono text-[4.5rem] leading-none font-bold tabular-nums md:text-[7rem]">{result.bpm}</span>
        <abbr title="beats per minute" className="font-mono text-[1.75rem] font-bold text-(--ds-muted) no-underline">
          BPM
        </abbr>
      </dd>
      <dd className="mt-1 text-lg">{averageLine(result.likely)}</dd>
    </>
  )
}
