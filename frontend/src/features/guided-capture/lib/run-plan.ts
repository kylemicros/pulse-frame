import { RUN_STOPPED_TEXT, VARIATION_LABEL } from "@/features/guided-capture/lib/run-copy"
import type { GuidedState, RunResult, Stage } from "@/features/guided-capture/types"

export const WARM_UP_MS = 60000
export const COUNTED_MS = 90000
export const RUN_MS = WARM_UP_MS + COUNTED_MS
export const TICK_MS = 250
export const RESULT_FRESH_MS = 10000

const MILESTONES: readonly { at: number; text: string }[] = [
  { at: 0, text: "Warm-up started. Stay in frame, no need to watch." },
  { at: WARM_UP_MS - 10000, text: "Counting starts in 10 seconds." },
  { at: WARM_UP_MS, text: "Counting started. Hold still for 90 seconds." },
  { at: WARM_UP_MS + COUNTED_MS / 2, text: "Counting is halfway there. Keep holding still." },
  { at: RUN_MS - 10000, text: "10 seconds left." },
]

export function elapsedMs(state: GuidedState): number {
  return state.status === "running" && state.startedAt !== null ? Math.max(0, state.now - state.startedAt) : 0
}

export function runStage(state: GuidedState): Stage {
  if (state.status === "done") {
    return "result"
  }
  if (state.status !== "running") {
    return "get-comfy"
  }
  return elapsedMs(state) < WARM_UP_MS ? "warm-up" : "counted"
}

export function secondsLeft(stage: Stage, elapsed: number): number {
  const end = stage === "warm-up" ? WARM_UP_MS : RUN_MS
  return Math.max(0, Math.ceil((end - elapsed) / 1000))
}

export function percentDone(elapsed: number, from: number, length: number): number {
  return Math.floor((Math.min(Math.max(elapsed - from, 0), length) / length) * 100)
}

function resultText(result: RunResult): string {
  if (result.kind === "none") {
    return "Done. No reading this time."
  }
  const parts = [`Done. Heart rate ${result.bpm} beats per minute.`]
  if (result.beatToBeatMs !== null) {
    parts.push(`${VARIATION_LABEL["beat-to-beat"]} ${result.beatToBeatMs} milliseconds.`)
  }
  if (result.overallMs !== null) {
    parts.push(`${VARIATION_LABEL.overall} ${result.overallMs} milliseconds.`)
  }
  return parts.join(" ")
}

export function milestoneText(state: GuidedState): string {
  if (state.status === "done" && state.result !== null) {
    return resultText(state.result)
  }
  if (state.status === "stopped" && state.endError === null) {
    return RUN_STOPPED_TEXT
  }
  if (state.status !== "running") {
    return ""
  }
  const elapsed = elapsedMs(state)
  return MILESTONES.findLast((milestone) => milestone.at <= elapsed)?.text ?? ""
}

export function tabTitle(state: GuidedState): string | null {
  const stage = runStage(state)
  if (stage === "result") {
    return "Done"
  }
  if (stage === "get-comfy") {
    return null
  }
  const left = secondsLeft(stage, elapsedMs(state))
  return stage === "warm-up" ? `Warm-up, ${left} s` : `Counting, ${left} s`
}
