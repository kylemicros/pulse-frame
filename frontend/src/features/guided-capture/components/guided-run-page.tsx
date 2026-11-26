import { cn } from "cn"
import { useCallback, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { PulseTrace } from "@/features/guided-capture/components/pulse-trace"
import { RunCamera } from "@/features/guided-capture/components/run-camera"
import { RunPanel } from "@/features/guided-capture/components/run-panel"
import { RunSteps } from "@/features/guided-capture/components/run-steps"
import { useGuidedRun } from "@/features/guided-capture/hooks/use-guided-run"
import { useHeldValue } from "@/features/guided-capture/hooks/use-held-value"
import { useWideLayout } from "@/features/guided-capture/hooks/use-wide-layout"
import { CALIBRATE_FLAG } from "@/features/guided-capture/lib/calibration-readout"
import { VIDEO_EMPTY } from "@/features/guided-capture/lib/empty-copy"
import { sceneHint, VIDEO_HINT } from "@/features/guided-capture/lib/reading-copy"
import {
  CAMERA_CUE,
  CAMERA_OFF_DONE,
  CAMERA_OFF_STOPPED,
  cameraOffAfter,
  PHASE_LINE,
} from "@/features/guided-capture/lib/run-copy"
import { elapsedMs, milestoneText } from "@/features/guided-capture/lib/run-plan"
import { setupPromptText } from "@/features/guided-capture/lib/setup-copy"
import type { GuidedState, Stage } from "@/features/guided-capture/types"

const STRIP: Record<Stage, string> = {
  "get-comfy": "bg-(--ds-track)",
  "warm-up": "bg-[repeating-linear-gradient(135deg,var(--ds-warm)_0_10px,var(--ds-track)_10px_16px)]",
  counted: "bg-(--ds-count)",
  result: "bg-(--ds-done)",
}

function cameraOffText(state: GuidedState, stage: Stage): string | null {
  const { monitor } = state
  if (monitor.phase === "running") {
    return null
  }
  if (stage === "result") {
    return CAMERA_OFF_DONE
  }
  if (state.endError !== null) {
    return cameraOffAfter(state.endError)
  }
  if (state.status === "stopped") {
    return CAMERA_OFF_STOPPED
  }
  return monitor.phase === "starting" ? VIDEO_EMPTY.starting : VIDEO_EMPTY.idle
}

function buttonLabel(state: GuidedState): "Start" | "Stop" | "Start again" {
  if (state.status === "starting" || state.status === "checking" || state.status === "running") {
    return "Stop"
  }
  return state.status === "idle" ? "Start" : "Start again"
}

export function GuidedRunPage() {
  const { state, stage, videoRef, start, stop, startAnyway, chimeOn, toggleChime } = useGuidedRun()
  const [calibrate] = useState(() => new URLSearchParams(globalThis.location.search).has(CALIBRATE_FLAG))
  const wide = useWideLayout()
  const mainButtonRef = useRef<HTMLButtonElement>(null)
  const focusMainButton = useCallback(() => mainButtonRef.current?.focus(), [])
  const hint = VIDEO_HINT[useHeldValue(sceneHint(state.monitor.scene))]
  const label = buttonLabel(state)
  const refShown = stage === "get-comfy" && state.endError !== null
  const stoppedLine = state.status === "stopped" && state.endError === null
  const camOn = state.status === "checking" || state.status === "running"
  const setupCue = state.check === null ? null : setupPromptText(state.check)
  const traceShown =
    (state.status === "checking" && state.check !== null) || stage === "warm-up" || stage === "counted"
  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-safe-4 pt-2 pb-4 font-sans text-base/normal text-(--ds-text) lg:flex lg:min-h-0 lg:max-w-none lg:flex-col lg:p-0">
      <div className="relative grid gap-4 overflow-hidden rounded-[10px] border border-(--ds-border) bg-(--ds-surface) px-4 pt-5.5 pb-4 md:gap-5 md:px-6 md:pt-7.5 md:pb-6 lg:min-h-0 lg:flex-1 lg:grid-rows-[auto_auto_minmax(0,1fr)] lg:gap-4 lg:rounded-none lg:border-x-0 lg:border-b-0 lg:bg-(--ds-bg) lg:px-safe-6 lg:pt-5 lg:pb-4">
        <div aria-hidden="true" className={cn("absolute inset-x-0 top-0 h-1.5", STRIP[stage])} />
        <div className="flex items-center justify-between gap-4">
          <p className="font-mono text-sm font-bold text-(--ds-muted)">{PHASE_LINE[stage]}</p>
          <div className="fixed inset-x-0 bottom-0 z-10 border-t border-(--ds-border) bg-(--ds-surface) px-safe-3 pt-3 pb-[calc(--spacing(3)+env(safe-area-inset-bottom))] md:static md:border-0 md:bg-transparent md:p-0">
            <Button
              ref={mainButtonRef}
              onClick={label === "Stop" ? stop : start}
              className="h-auto min-h-11 w-full rounded-md border-2 border-(--ds-primary-bg) bg-(--ds-primary-bg) px-5 py-2.5 text-base font-bold text-(--ds-primary-text) hover:bg-(--ds-primary-bg) hover:opacity-90 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count) md:w-auto md:min-w-40"
            >
              {label}
            </Button>
          </div>
        </div>
        <RunSteps stage={stage} />
        <div className="grid gap-4 md:gap-6 lg:min-h-0 [--panel-width:384px] min-[1920px]:[--panel-width:440px] lg:grid-cols-[minmax(0,1fr)_var(--panel-width)]">
          <div className="flex min-w-0 flex-col gap-3 lg:grid lg:min-h-0 lg:grid-rows-[minmax(0,1fr)_auto]">
            <div className="min-w-0 lg:min-h-0 lg:@container-size">
              <RunCamera
                videoRef={videoRef}
                live={state.monitor.phase === "running"}
                scene={camOn ? state.monitor.scene : null}
                offText={cameraOffText(state, stage)}
                cue={refShown || state.check !== null ? null : CAMERA_CUE[stage]}
                setupCue={setupCue}
              />
            </div>
            {wide ? (
              <div className="h-32 flex-none">
                {traceShown ? <PulseTrace samples={state.monitor.samples} /> : null}
              </div>
            ) : null}
          </div>
          <div
            data-testid="run-panel"
            className="relative flex min-w-0 flex-col gap-4 lg:min-h-0 lg:gap-0 lg:overflow-hidden lg:rounded-[10px] lg:border lg:border-(--ds-border) lg:bg-(--ds-surface)"
          >
            <output data-testid="milestone-status" className={stoppedLine ? "block lg:px-5 lg:pt-5" : "sr-only"}>
              {milestoneText(state)}
            </output>
            <RunPanel
              wide={wide}
              state={state}
              stage={stage}
              elapsed={elapsedMs(state)}
              hint={state.status === "running" ? hint : null}
              chimeOn={chimeOn}
              onToggleChime={toggleChime}
              onStartAnyway={startAnyway}
              onFocusLeave={focusMainButton}
              calibrate={calibrate}
            />
          </div>
        </div>
      </div>
    </main>
  )
}
