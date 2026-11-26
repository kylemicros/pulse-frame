import { initialMonitorState, monitorReducer } from "@/features/guided-capture/lib/monitor-reducer"
import { noReadingReason } from "@/features/guided-capture/lib/run-copy"
import { RESULT_FRESH_MS, RUN_MS } from "@/features/guided-capture/lib/run-plan"
import {
  addSetupSample,
  advanceSetupCheck,
  newSetupCheck,
  restartSetupSpeed,
  setupFps,
  setupPassed,
  type SetupCheck,
} from "@/features/guided-capture/lib/setup-check"
import type { CheckEnd, GuidedAction, GuidedState, MonitorState, RunResult } from "@/features/guided-capture/types"

export const initialGuidedState: GuidedState = {
  monitor: initialMonitorState,
  status: "idle",
  pressedAt: null,
  startedAt: null,
  check: null,
  checkEnd: null,
  now: 0,
  result: null,
  lastGoodBpm: null,
  haltError: null,
  endError: null,
  checkStopped: false,
}

function runResult(monitor: MonitorState, end: number): RunResult {
  const { variation } = monitor
  const last = monitor.link === "live" && variation !== null && end - variation.t <= RESULT_FRESH_MS ? variation : null
  if (last === null || last.minute_bpm === null) {
    return { kind: "none", why: noReadingReason(last), clearPercent: last?.clear_percent ?? null }
  }
  const low = last.bpm_low === null ? null : Math.floor(last.bpm_low)
  const high = last.bpm_high === null ? null : Math.ceil(last.bpm_high)
  return {
    kind: "reading",
    bpm: Math.round(last.minute_bpm),
    likely: low !== null && high !== null && low < high ? { low, high } : null,
    beatToBeatMs: last.rmssd_ms === null ? null : Math.round(last.rmssd_ms),
    overallMs: last.sdnn_ms === null ? null : Math.round(last.sdnn_ms),
  }
}

function beginRun(state: GuidedState, check: SetupCheck, at: number, how: CheckEnd["how"]): GuidedState {
  const checkEnd: CheckEnd = {
    sample: check.sample,
    fps: setupFps(check, at),
    how,
    tookMs: at - (state.pressedAt ?? check.startedAt),
  }
  return { ...state, status: "running", check: null, checkEnd, startedAt: at, now: at }
}

function checkAt(state: GuidedState, check: SetupCheck, at: number): GuidedState {
  return setupPassed(check, at) ? beginRun(state, check, at, "passed") : { ...state, check, now: at }
}

function tick(state: GuidedState, at: number): GuidedState {
  if (state.status === "checking" && state.check !== null) {
    return checkAt(state, advanceSetupCheck(state.check, at), at)
  }
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
    return { ...state, monitor, status: "checking", check: newSetupCheck(action.at), now: action.at }
  }
  if (event.type === "ended") {
    if (state.status === "done") {
      return { ...state, monitor }
    }
    const endError = event.error ?? state.haltError
    const checkFailed = state.status === "checking" && event.error !== null
    const stopped = state.status === "running" || checkFailed || state.haltError !== null
    const checkStopped = !stopped && state.status === "checking" && endError === null
    return { ...state, monitor, status: stopped ? "stopped" : "idle", check: null, endError, haltError: null, checkStopped }
  }
  if (event.type === "link" && event.status !== "live" && state.check !== null) {
    return { ...state, monitor, check: advanceSetupCheck(restartSetupSpeed(state.check), action.at) }
  }
  if (event.type === "setup-sample") {
    if (state.status !== "checking" || state.check === null) {
      return state
    }
    return checkAt(state, addSetupSample(state.check, event.sample, action.at), action.at)
  }
  if (event.type === "message" && event.message.type === "bpm" && event.message.state === "ok") {
    return { ...state, monitor, lastGoodBpm: event.message.bpm ?? state.lastGoodBpm }
  }
  return { ...state, monitor }
}

export function guidedReducer(state: GuidedState, action: GuidedAction): GuidedState {
  switch (action.type) {
    case "start":
      return {
        ...initialGuidedState,
        monitor: monitorReducer(state.monitor, { type: "start" }),
        status: "starting",
        pressedAt: action.at,
      }
    case "session":
      return applySession(state, action)
    case "tick":
      return tick(state, action.at)
    case "halt":
      return state.haltError === null ? { ...state, haltError: action.error } : state
    case "start-anyway":
      return state.status === "checking" && state.check !== null
        ? beginRun(state, state.check, action.at, "anyway")
        : state
    case "notice-expired":
      return { ...state, monitor: monitorReducer(state.monitor, action) }
  }
}
