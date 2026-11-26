import { LiveReadings } from "@/features/guided-capture/components/live-readings"
import { PulseTrace } from "@/features/guided-capture/components/pulse-trace"
import { RunAlerts } from "@/features/guided-capture/components/run-alerts"
import { RunPlanList } from "@/features/guided-capture/components/run-plan-list"
import { RunProgress } from "@/features/guided-capture/components/run-progress"
import { RunResults } from "@/features/guided-capture/components/run-results"
import { SetupCheckStatus } from "@/features/guided-capture/components/setup-check-status"
import { ToggleButton } from "@/features/guided-capture/components/toggle-button"
import { WATCH_TIP } from "@/features/guided-capture/lib/run-copy"
import type { GuidedState, Stage } from "@/features/guided-capture/types"

const HEADLINE = "text-2xl leading-tight font-bold md:text-[1.75rem]"

type RunPanelProps = {
  state: GuidedState
  stage: Stage
  elapsed: number
  hint: string | null
  chimeOn: boolean
  onToggleChime: () => void
  onStartAnyway: () => void
  onFocusLeave: () => void
}

export function RunPanel({
  state,
  stage,
  elapsed,
  hint,
  chimeOn,
  onToggleChime,
  onStartAnyway,
  onFocusLeave,
}: RunPanelProps) {
  if (state.status === "checking" && state.check !== null) {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        <h2 className={HEADLINE}>{state.check.shown === "allGood" ? "Looking good" : "Quick setup check"}</h2>
        <SetupCheckStatus
          check={state.check}
          now={state.now}
          onStartAnyway={onStartAnyway}
          onFocusLeave={onFocusLeave}
        />
        <RunAlerts errors={[state.monitor.error, state.monitor.notice]} />
        <LiveReadings monitor={state.monitor} lastGoodBpm={state.lastGoodBpm} stage="warm-up" />
        <PulseTrace samples={state.monitor.samples} />
      </div>
    )
  }
  if (stage === "warm-up" || stage === "counted") {
    const warmUp = stage === "warm-up"
    return (
      <div className="flex min-w-0 flex-col gap-4">
        <h2 className={HEADLINE}>{warmUp ? "Stay in frame. No need to watch." : "Counting. Hold still."}</h2>
        <p>
          {warmUp
            ? "Look out the window, think about lunch. Counting starts on its own, and we'll tell you."
            : "Breathe like normal. We'll tell you when it's done."}
        </p>
        <RunProgress stage={stage} elapsed={elapsed} />
        {hint === null ? null : (
          <p className="rounded-md border border-l-4 border-(--ds-edge) border-l-(--ds-count) bg-(--ds-surface) px-3 py-2.5">
            {hint}
          </p>
        )}
        <RunAlerts errors={[state.monitor.error, state.monitor.notice]} />
        <LiveReadings monitor={state.monitor} lastGoodBpm={state.lastGoodBpm} stage={stage} />
        <PulseTrace samples={state.monitor.samples} />
      </div>
    )
  }
  if (stage === "result" && state.result !== null) {
    const { result } = state
    return (
      <div className="flex min-w-0 flex-col gap-4">
        <h2 className={HEADLINE}>{result.kind === "reading" ? "Done. Nice sitting." : "Done, but no reading this time."}</h2>
        <p>
          {result.kind === "reading"
            ? "90 seconds of holding still, which is harder than it sounds."
            : `${result.why.message} ${result.why.action}`}
        </p>
        <RunResults result={result} />
        {result.kind === "reading" ? (
          <p>{WATCH_TIP}</p>
        ) : (
          <p className="font-mono text-sm text-(--ds-muted)">{`Ref: ${result.why.code}`}</p>
        )}
      </div>
    )
  }
  if (state.endError !== null) {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        <RunAlerts errors={[state.endError]} />
        <RunResults result={null} />
      </div>
    )
  }
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <h2 className={HEADLINE}>Two and a half minutes, mostly doing nothing.</h2>
      <RunPlanList />
      <p>Leave your watch alone during the run. Check its history afterwards.</p>
      <ToggleButton label="Chime at start and end" pressed={chimeOn} onToggle={onToggleChime} />
      <RunResults result={null} />
    </div>
  )
}
