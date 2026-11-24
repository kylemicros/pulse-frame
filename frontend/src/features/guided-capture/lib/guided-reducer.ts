import { initialMonitorState, monitorReducer, type MonitorState } from "@/features/monitor"
import { NO_READING_FACE, NO_READING_PULSE } from "@/features/guided-capture/lib/run-copy"
import { FRESH_READING_MS, RESULT_WINDOW_MS, RUN_MS } from "@/features/guided-capture/lib/run-plan"
import type { GuidedAction, GuidedState, RunResult, WindowTotals } from "@/features/guided-capture/types"

const EMPTY_TOTALS: WindowTotals = { okMs: 0, bpmMs: 0, noFaceMs: 0 }

export const initialGuidedState: GuidedState = {
  monitor: initialMonitorState,
  status: "idle",
  startedAt: null,
  now: 0,
  totals: EMPTY_TOTALS,
  result: null,
  lastGoodBpm: null,
  haltError: null,
  endError: null,
}

function freshBpm(monitor: MonitorState, at: number): number | null {
  const { reading } = monitor
  if (reading?.state !== "ok" || reading.bpm === null) {
    return null
  }
  return at - reading.t <= FRESH_READING_MS ? reading.bpm : null
}

function addSpan(totals: WindowTotals, monitor: MonitorState, spanMs: number, at: number): WindowTotals {
  if (spanMs <= 0 || monitor.link !== "live") {
    return totals
  }
  const bpm = freshBpm(monitor, at)
  const { scene } = monitor
  return {
    okMs: totals.okMs + (bpm === null ? 0 : spanMs),
    bpmMs: totals.bpmMs + (bpm === null ? 0 : bpm * spanMs),
    noFaceMs: totals.noFaceMs + (scene !== null && !scene.face ? spanMs : 0),
  }
}

function runResult(totals: WindowTotals): RunResult {
  if (totals.okMs > 0) {
    return { kind: "reading", bpm: Math.round(totals.bpmMs / totals.okMs) }
  }
  return { kind: "none", why: totals.noFaceMs * 2 >= RESULT_WINDOW_MS ? NO_READING_FACE : NO_READING_PULSE }
}

function tick(state: GuidedState, at: number): GuidedState {
  if (state.status !== "running" || state.startedAt === null) {
    return state
  }
  const windowStart = state.startedAt + RUN_MS - RESULT_WINDOW_MS
  const windowEnd = state.startedAt + RUN_MS
  const span = Math.min(at, windowEnd) - Math.max(state.now, windowStart)
  const totals = addSpan(state.totals, state.monitor, span, Math.min(at, windowEnd))
  if (at - state.startedAt >= RUN_MS) {
    return { ...state, now: at, totals, status: "done", result: runResult(totals) }
  }
  return { ...state, now: at, totals }
}

function applySession(state: GuidedState, action: Extract<GuidedAction, { type: "session" }>): GuidedState {
  const { event } = action
  const monitor = monitorReducer(state.monitor, event)
  if (event.type === "running") {
    return { ...state, monitor, status: "running", startedAt: action.at, now: action.at }
  }
  if (event.type === "ended") {
    if (state.status === "done") {
      return { ...state, monitor }
    }
    const endError = event.error ?? state.haltError
    const stopped = state.status === "running" || state.haltError !== null
    return { ...state, monitor, status: stopped ? "stopped" : "idle", endError, haltError: null }
  }
  if (event.type === "message" && event.message.type === "bpm" && event.message.state === "ok") {
    return { ...state, monitor, lastGoodBpm: event.message.bpm ?? state.lastGoodBpm }
  }
  return { ...state, monitor }
}

export function guidedReducer(state: GuidedState, action: GuidedAction): GuidedState {
  switch (action.type) {
    case "start":
      return { ...initialGuidedState, monitor: monitorReducer(state.monitor, { type: "start" }), status: "starting" }
    case "session":
      return applySession(state, action)
    case "tick":
      return tick(state, action.at)
    case "halt":
      return state.haltError === null ? { ...state, haltError: action.error } : state
    case "notice-expired":
      return { ...state, monitor: monitorReducer(state.monitor, action) }
  }
}
