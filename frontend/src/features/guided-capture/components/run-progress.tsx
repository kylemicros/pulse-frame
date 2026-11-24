import { RunBar } from "@/features/guided-capture/components/run-bar"
import { COUNTED_MS, percentDone, secondsLeft, WARM_UP_MS } from "@/features/guided-capture/lib/run-plan"

type RunProgressProps = {
  stage: "warm-up" | "counted"
  elapsed: number
}

function barText(name: string, percent: number, left: number, started: boolean): string {
  if (!started) {
    return `${name} 0 percent, not started`
  }
  return percent >= 100 ? `${name} 100 percent, done` : `${name} ${percent} percent, ${left} seconds left`
}

export function RunProgress({ stage, elapsed }: RunProgressProps) {
  const left = secondsLeft(stage, elapsed)
  const warmUp = percentDone(elapsed, 0, WARM_UP_MS)
  const counted = percentDone(elapsed, WARM_UP_MS, COUNTED_MS)
  const timerLabel = stage === "warm-up" ? "Time until counting starts" : "Time until done"
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <span role="timer" aria-label={timerLabel} className="font-mono text-5xl leading-none font-bold tabular-nums">
          {`${left} s`}
        </span>
        <span className="text-(--ds-muted)">{stage === "warm-up" ? "until counting starts" : "until done"}</span>
      </div>
      <div className="flex gap-2">
        <div className="min-w-0 flex-60">
          <RunBar
            label="Warm-up"
            labelShown
            percent={warmUp}
            valueText={barText("Warm-up", warmUp, secondsLeft("warm-up", elapsed), true)}
            fillClassName="bg-(--ds-warm)"
          />
        </div>
        <div className="min-w-0 flex-90">
          <RunBar
            label="Counted"
            labelShown
            percent={counted}
            valueText={barText("Counted", counted, secondsLeft("counted", elapsed), stage === "counted")}
            fillClassName="bg-(--ds-count)"
          />
        </div>
      </div>
    </div>
  )
}
