import type { RunResult } from "@/features/guided-capture/types"

type ResultHeartRateProps = {
  result: RunResult | null
}

export function ResultHeartRate({ result }: ResultHeartRateProps) {
  if (result === null) {
    return <dd className="text-lg font-bold">No reading yet</dd>
  }
  if (result.kind === "none") {
    return (
      <>
        <dd className="text-lg font-bold">No reading this time</dd>
        <dd className="text-sm text-(--ds-muted)">Last counted minute.</dd>
      </>
    )
  }
  return (
    <>
      <dd>
        <span className="font-mono text-[3.5rem] leading-[1.1] font-bold tabular-nums">{result.bpm}</span>
        <abbr title="beats per minute" className="ml-1.5 font-mono font-bold text-(--ds-muted) no-underline">
          BPM
        </abbr>
      </dd>
      <dd className="text-sm text-(--ds-muted)">Average over the last counted minute.</dd>
    </>
  )
}
