import { cn } from "cn"
import { useCallback, useLayoutEffect, useRef, useState, type AnimationEvent, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { PulseTrace } from "@/features/guided-capture/components/pulse-trace"
import { RunCamera } from "@/features/guided-capture/components/run-camera"
import { RunPanel } from "@/features/guided-capture/components/run-panel"
import { RunResults } from "@/features/guided-capture/components/run-results"
import { RunSteps } from "@/features/guided-capture/components/run-steps"
import { SetupPromptBox } from "@/features/guided-capture/components/setup-prompt-box"
import { SettingsMenu, type SettingSwitchItem } from "@/features/settings"
import { useGuidedRun } from "@/features/guided-capture/hooks/use-guided-run"
import { useHeldValue } from "@/features/guided-capture/hooks/use-held-value"
import { useTabletUp, useWideLayout } from "@/features/guided-capture/hooks/use-wide-layout"
import { CALIBRATE_FLAG } from "@/features/guided-capture/lib/calibration-readout"
import { CAMERA_WAKING, IDLE_CAMERA_LABEL, IDLE_HEADLINE } from "@/features/guided-capture/lib/empty-copy"
import { sceneHint, VIDEO_HINT } from "@/features/guided-capture/lib/reading-copy"
import {
  CAMERA_CUE,
  CAMERA_OFF_STOPPED,
  CALIBRATION_LINE_START,
  cameraOffAfter,
  CHIME_LINE,
  SKIN_OUTLINE_LINE,
} from "@/features/guided-capture/lib/run-copy"
import { elapsedMs, milestoneText, stoppedStage } from "@/features/guided-capture/lib/run-plan"
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
  if (monitor.phase === "running" || stage === "result") {
    return null
  }
  if (state.endError !== null) {
    return cameraOffAfter(state.endError)
  }
  if (state.status === "stopped") {
    return CAMERA_OFF_STOPPED
  }
  return monitor.phase === "starting" ? CAMERA_WAKING : null
}

function buttonLabel(state: GuidedState): "Start" | "Stop" | "Start again" {
  if (state.status === "starting" || state.status === "checking" || state.status === "running") {
    return "Stop"
  }
  return state.status === "idle" ? "Start" : "Start again"
}

type GuidedRunPageProps = {
  brand: ReactNode
}

export function GuidedRunPage({ brand }: GuidedRunPageProps) {
  const { state, stage, videoRef, start, stop, startAnyway, chimeOn, setChime } = useGuidedRun()
  const [calibrate] = useState(() => new URLSearchParams(globalThis.location.search).has(CALIBRATE_FLAG))
  const [outlineOn, setOutlineOn] = useState(true)
  const [calibrationOn, setCalibrationOn] = useState(true)
  const wide = useWideLayout()
  const tabletUp = useTabletUp()
  const popoverHomeRef = useRef<HTMLDivElement>(null)
  const cameraHomeRef = useRef<HTMLDivElement>(null)
  const mainButtonRef = useRef<HTMLButtonElement>(null)
  const focusMainButton = useCallback(() => mainButtonRef.current?.focus(), [])
  const hint = VIDEO_HINT[useHeldValue(sceneHint(state.monitor.scene))]
  const label = buttonLabel(state)
  const refShown = stage === "get-comfy" && state.endError !== null
  const stoppedLine = state.status === "stopped" && state.endError === null
  const camOn = state.status === "checking" || state.status === "running"
  const setupCue = state.check === null ? null : setupPromptText(state.check)
  const cue = refShown || state.check !== null ? null : (CAMERA_CUE[stage] ?? null)
  const idle = state.status === "idle" && state.endError === null
  const result = stage === "result" ? state.result : null
  const errorShown = state.endError !== null && result === null
  const idleHeadline = (
    <p className="text-[1.75rem] leading-[1.15] font-extrabold tracking-[-0.015em] md:text-[2.125rem]">
      {IDLE_HEADLINE}
    </p>
  )
  const alertFirst = !wide && errorShown
  const resultShown = result !== null
  const [cameraGone, setCameraGone] = useState(false)
  const [hadResult, setHadResult] = useState(resultShown)
  if (hadResult !== resultShown) {
    setHadResult(resultShown)
    setCameraGone(false)
  }
  const hideCamera = (event: AnimationEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) {
      setCameraGone(true)
    }
  }
  useLayoutEffect(() => {
    if (resultShown && cameraHomeRef.current?.contains(document.activeElement)) {
      focusMainButton()
    }
  }, [resultShown, focusMainButton])
  const panel = (
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
        onStartAnyway={startAnyway}
        onFocusLeave={focusMainButton}
        calibrate={calibrate && calibrationOn}
        cuesUnderCamera={!tabletUp}
      />
    </div>
  )
  const traceShown =
    (state.status === "checking" && state.check !== null) || stage === "warm-up" || stage === "counted"
  const switches: SettingSwitchItem[] = [
    { name: "Skin outline", line: SKIN_OUTLINE_LINE, checked: outlineOn, onCheckedChange: setOutlineOn },
    { name: "Chime", line: CHIME_LINE, checked: chimeOn, onCheckedChange: setChime },
  ]
  const trailingSwitches: SettingSwitchItem[] = calibrate
    ? [
        {
          name: "Calibration numbers",
          line: (
            <>
              {CALIBRATION_LINE_START} <span className="whitespace-nowrap">?calibrate.</span>
            </>
          ),
          checked: calibrationOn,
          onCheckedChange: setCalibrationOn,
        },
      ]
    : []
  const mainButton = (
    <Button
      ref={mainButtonRef}
      onClick={label === "Stop" ? stop : start}
      className="h-auto min-h-11 w-full rounded-md border-2 border-(--ds-primary-bg) bg-(--ds-primary-bg) px-5 py-2.5 font-sans text-base font-bold text-(--ds-primary-text) hover:border-(--ds-primary-hover) hover:bg-(--ds-primary-hover) motion-reduce:transition-none focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count) md:w-auto md:min-w-40"
    >
      {label}
    </Button>
  )
  return (
    <>
      <header className="flex w-full flex-none flex-wrap items-center gap-x-6 gap-y-2.5 border-b border-(--ds-border) bg-(--ds-surface) px-safe-4 py-2.5 font-sans lg:flex-nowrap lg:px-safe-6">
        <div className="min-w-0 flex-1 lg:flex-none">{brand}</div>
        <RunSteps
          stage={stage}
          stopped={stoppedStage(state)}
          className="order-last w-full lg:order-none lg:ml-auto lg:w-auto"
        />
        <div className="relative flex flex-none items-center gap-2">
          <SettingsMenu
            switches={switches}
            trailingSwitches={trailingSwitches}
            sheet={!tabletUp}
            container={popoverHomeRef}
          />
          {tabletUp ? mainButton : null}
          <div ref={popoverHomeRef} className="absolute top-full right-0" />
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-safe-4 pt-4 pb-4 font-sans text-base/normal text-(--ds-text) lg:flex lg:min-h-0 lg:max-w-none lg:flex-col lg:p-0">
        <div className="relative grid gap-4 overflow-hidden rounded-[10px] border border-(--ds-border) bg-(--ds-surface) px-4 pt-5.5 pb-4 md:gap-5 md:px-6 md:pt-7.5 md:pb-6 lg:min-h-0 lg:flex-1 lg:grid-rows-[minmax(0,1fr)] lg:gap-4 lg:rounded-none lg:border-0 lg:bg-(--ds-bg) lg:px-safe-6 lg:pt-5 lg:pb-4">
          <div aria-hidden="true" className={cn("absolute inset-x-0 top-0 h-1.5", STRIP[stage])} />
          {tabletUp ? null : (
            <div className="fixed inset-x-0 bottom-0 z-10 border-t border-(--ds-border) bg-(--ds-surface) px-safe-3 pt-3 pb-[calc(--spacing(3)+env(safe-area-inset-bottom))]">
              {mainButton}
            </div>
          )}
          <div className="grid gap-4 md:gap-6 lg:min-h-0 [--panel-width:384px] min-[1920px]:[--panel-width:440px] lg:grid-cols-[minmax(0,1fr)_var(--panel-width)]">
            {alertFirst ? panel : null}
            <div
              className={cn(
                "relative flex min-w-0 flex-col gap-3 lg:grid lg:min-h-0",
                result === null ? "lg:grid-rows-[minmax(0,1fr)_auto]" : "lg:grid-rows-[minmax(0,1fr)]",
              )}
            >
              <div
                ref={cameraHomeRef}
                inert={resultShown}
                onAnimationEnd={hideCamera}
                className={cn(
                  "min-w-0 lg:min-h-0 lg:@container-size",
                  resultShown &&
                    (cameraGone
                      ? "hidden"
                      : "pointer-events-none absolute inset-x-0 top-0 animate-phase-out motion-reduce:hidden lg:bottom-[calc(--spacing(32)+--spacing(3))]"),
                )}
              >
                <RunCamera
                  videoRef={videoRef}
                  live={state.monitor.phase === "running"}
                  shown={result === null}
                  scene={camOn ? state.monitor.scene : null}
                  offText={cameraOffText(state, stage)}
                  hiddenLabel={idle ? IDLE_CAMERA_LABEL : null}
                  cue={tabletUp ? cue : null}
                  setupCue={tabletUp ? setupCue : null}
                  outlineOn={outlineOn}
                />
              </div>
              {!tabletUp && state.status === "checking" && state.check !== null ? (
                <SetupPromptBox check={state.check} now={state.now} promptOnCamera={false} />
              ) : null}
              {!tabletUp && cue !== null ? (
                <p className="rounded-md border border-(--ds-edge) bg-(--ds-surface) px-3.5 py-2 text-[0.9375rem] text-(--ds-text)">
                  {cue}
                </p>
              ) : null}
              {result === null ? null : <RunResults result={result} />}
              {wide && result === null ? (
                <div className={cn("h-32 flex-none", idle && "flex flex-col justify-center")}>
                  {traceShown ? <PulseTrace samples={state.monitor.samples} /> : null}
                  {idle ? idleHeadline : null}
                </div>
              ) : null}
              {!wide && idle ? idleHeadline : null}
            </div>
            {alertFirst ? null : panel}
          </div>
        </div>
      </main>
    </>
  )
}
