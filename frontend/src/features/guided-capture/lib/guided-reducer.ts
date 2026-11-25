import { initialMonitorState, monitorReducer } from "@/features/guided-capture/lib/monitor-reducer"
import { noReadingReason } from "@/features/guided-capture/lib/run-copy"
import { RESULT_FRESH_MS, RUN_MS } from "@/features/guided-capture/lib/run-plan"
import type { GuidedAction, GuidedState, MonitorState, RunResult } from "@/features/guided-capture/types"

export const initialGuidedState: GuidedState = {
  monitor: initialMonitorState,
  status: "idle",
  startedAt: null,
  now: 0,
  result: null,
  lastGoodBpm: null,
  haltError: null,
  endError: null,
}

function runResult(monitor: MonitorState, end: number): RunResult {
  const { variation } = monitor
  const last = monitor.link === "live" && variation !== null && end - variation.t <= RESULT_FRESH_MS ? variation : null
  if (last === null || last.minute_bpm === null) {
    return { kind: "none", why: noReadingReason(last) }
  }
  return {
    kind: "reading",
    bpm: Math.round(last.minute_bpm),
    beatToBeatMs: last.rmssd_ms === null ? null : Math.round(last.rmssd_ms),
    overallMs: last.sdnn_ms === null ? null : Math.round(last.sdnn_ms),
  }
}

function tick(state: GuidedState, at: number): GuidedState {
  if (state.status !== "running" || state.startedAt === null) {
    return state
  }
  const end = state.startedAt + RUN_MS
  if (at >= end) {
    return { ...state, now: at, status: "done", result: runResult(state.monitor, end) }
  }
  return { ...state, now: at }
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
