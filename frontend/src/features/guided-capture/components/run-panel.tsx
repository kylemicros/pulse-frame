import { CalibrationReadout } from "@/features/guided-capture/components/calibration-readout"
import { LiveReadings } from "@/features/guided-capture/components/live-readings"
import { PanelLayout } from "@/features/guided-capture/components/panel-layout"
import { PulseTrace } from "@/features/guided-capture/components/pulse-trace"
import { RunAlerts } from "@/features/guided-capture/components/run-alerts"
import { RunPlanList } from "@/features/guided-capture/components/run-plan-list"
import { RunProgress } from "@/features/guided-capture/components/run-progress"
import { RunResults } from "@/features/guided-capture/components/run-results"
import { SetupCheckPrompt } from "@/features/guided-capture/components/setup-check-prompt"
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
  calibrate: boolean
  wide: boolean
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
  calibrate,
  wide,
}: RunPanelProps) {
  const readout = calibrate ? (
    <CalibrationReadout check={state.check} now={state.now} checkEnd={state.checkEnd} result={state.result} />
  ) : null
  const trace = wide ? null : <PulseTrace samples={state.monitor.samples} />
  if (state.status === "checking" && state.check !== null) {
    return (
      <PanelLayout
        label="Setup check details"
        wide={wide}
        head={
          <>
            <h2 className={HEADLINE}>{state.check.shown === "allGood" ? "Looking good" : "Quick setup check"}</h2>
            <SetupCheckPrompt check={state.check} now={state.now} />
            <RunAlerts errors={[state.monitor.error, state.monitor.notice]} />
          </>
        }
        main={
          <SetupCheckStatus
            check={state.check}
            now={state.now}
            onStartAnyway={onStartAnyway}
            onFocusLeave={onFocusLeave}
          />
        }
        side={
          <>
            <LiveReadings monitor={state.monitor} lastGoodBpm={state.lastGoodBpm} stage="warm-up" />
            {trace}
          </>
        }
        readout={readout}
      />
    )
  }
  if (stage === "warm-up" || stage === "counted") {
    const warmUp = stage === "warm-up"
    return (
      <PanelLayout
        label={warmUp ? "Warm-up details" : "Counting details"}
        wide={wide}
        head={
          <>
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
          </>
        }
        side={
          <>
            <LiveReadings monitor={state.monitor} lastGoodBpm={state.lastGoodBpm} stage={stage} />
            {trace}
          </>
        }
        readout={readout}
      />
    )
  }
  if (stage === "result" && state.result !== null) {
    const { result } = state
    const reading = result.kind === "reading"
    return (
      <PanelLayout
        label="Run details"
        wide={wide}
        head={
          <>
            <h2 className={HEADLINE}>{reading ? "Done. Nice sitting." : "Done, but no reading this time."}</h2>
            {reading ? null : <p>{`${result.why.message} ${result.why.action}`}</p>}
          </>
        }
        main={
          <>
            {reading ? <p>90 seconds of holding still, which is harder than it sounds.</p> : null}
            <RunResults result={result} />
            {reading ? (
              <p>{WATCH_TIP}</p>
            ) : (
              <p className="font-mono text-sm text-(--ds-muted)">{`Ref: ${result.why.code}`}</p>
            )}
          </>
        }
        readout={readout}
      />
    )
  }
  if (state.endError !== null) {
    return (
      <PanelLayout
        label="Run details"
        wide={wide}
        main={
          <>
            <RunAlerts errors={[state.endError]} />
            <RunResults result={null} />
          </>
        }
        readout={null}
      />
    )
  }
  return (
    <PanelLayout
      label="Run plan"
      wide={wide}
      head={<h2 className={HEADLINE}>Two and a half minutes, mostly doing nothing.</h2>}
      main={
        <>
          <RunPlanList />
          <p>Leave your watch alone during the run. Check its history afterwards.</p>
          <ToggleButton label="Chime at start and end" pressed={chimeOn} onToggle={onToggleChime} />
          <RunResults result={null} />
        </>
      }
      readout={null}
    />
  )
}
