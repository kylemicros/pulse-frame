import { cn } from "cn"
import { Button } from "@/components/ui/button"
import { RunCamera } from "@/features/guided-capture/components/run-camera"
import { RunPanel } from "@/features/guided-capture/components/run-panel"
import { RunSteps } from "@/features/guided-capture/components/run-steps"
import { useGuidedRun } from "@/features/guided-capture/hooks/use-guided-run"
import {
  CAMERA_CUE,
  CAMERA_OFF_DONE,
  CAMERA_OFF_STOPPED,
  cameraOffAfter,
  DISCLAIMER,
  PHASE_LINE,
} from "@/features/guided-capture/lib/run-copy"
import { elapsedMs, milestoneText } from "@/features/guided-capture/lib/run-plan"
import type { GuidedState, Stage } from "@/features/guided-capture/types"
import { sceneHint, useHeldValue, VIDEO_EMPTY, VIDEO_HINT } from "@/features/monitor"

const STRIP: Record<Stage, string> = {
  "get-comfy": "bg-(--ds-track)",
  "warm-up": "bg-[repeating-linear-gradient(135deg,var(--ds-warm)_0_10px,var(--ds-track)_10px_16px)]",
  counted: "bg-(--ds-count)",
  result: "bg-(--ds-done)",
}

type GuidedRunPageProps = {
  active: boolean
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
  if (state.status === "starting" || state.status === "running") {
    return "Stop"
  }
  return state.status === "idle" ? "Start" : "Start again"
}

export function GuidedRunPage({ active }: GuidedRunPageProps) {
  const { state, stage, videoRef, start, stop, chimeOn, toggleChime } = useGuidedRun(active)
  const hint = VIDEO_HINT[useHeldValue(sceneHint(state.monitor.scene))]
  if (!active) {
    return null
  }
  const label = buttonLabel(state)
  const refShown = stage === "get-comfy" && state.endError !== null
  const stoppedLine = state.status === "stopped" && state.endError === null
  return (
    <main className="mx-auto w-full max-w-6xl px-4 pt-2 pb-24 font-sans text-base/normal text-(--ds-text) md:pb-8">
      <div className="relative grid gap-4 overflow-hidden rounded-[10px] border border-(--ds-border) bg-(--ds-surface) px-4 pt-5.5 pb-4 md:gap-5 md:px-6 md:pt-7.5 md:pb-6">
        <div aria-hidden="true" className={cn("absolute inset-x-0 top-0 h-1.5", STRIP[stage])} />
        <div className="flex items-center justify-between gap-4">
          <p className="font-mono text-sm font-bold text-(--ds-muted)">{PHASE_LINE[stage]}</p>
          <div className="fixed inset-x-0 bottom-0 z-10 border-t border-(--ds-border) bg-(--ds-surface) p-3 md:static md:border-0 md:bg-transparent md:p-0">
            <Button
              onClick={label === "Stop" ? stop : start}
              className="h-auto min-h-11 w-full rounded-md border-2 border-(--ds-primary-bg) bg-(--ds-primary-bg) px-5 py-2.5 text-base font-bold text-(--ds-primary-text) hover:bg-(--ds-primary-bg) hover:opacity-90 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count) md:w-auto md:min-w-40"
            >
              {label}
            </Button>
          </div>
        </div>
        <RunSteps stage={stage} />
        <div className="grid gap-4 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] md:items-start md:gap-6">
          <RunCamera
            videoRef={videoRef}
            live={state.monitor.phase === "running"}
            offText={cameraOffText(state, stage)}
            cue={refShown ? null : CAMERA_CUE[stage]}
          />
          <div className="relative flex min-w-0 flex-col gap-4">
            <output data-testid="milestone-status" className={stoppedLine ? "block" : "sr-only"}>
              {milestoneText(state)}
            </output>
            <RunPanel
              state={state}
              stage={stage}
              elapsed={elapsedMs(state)}
              hint={state.status === "running" ? hint : null}
              chimeOn={chimeOn}
              onToggleChime={toggleChime}
            />
          </div>
        </div>
        <p className="border-t border-(--ds-border) pt-3 text-sm text-(--ds-muted)">{DISCLAIMER}</p>
      </div>
    </main>
  )
}
