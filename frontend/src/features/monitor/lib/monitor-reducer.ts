import { BAD_REPLY, SOCKET_UNAVAILABLE } from "@/lib/socket/socket-errors"
import type { MonitorAction, MonitorState } from "@/features/monitor/types"

export const initialMonitorState: MonitorState = {
  phase: "idle",
  link: null,
  scene: null,
  latestT: null,
  reading: null,
  acquiringSince: null,
  samples: [],
  error: null,
  notice: null,
}

const CLEARED_READINGS = {
  scene: null,
  latestT: null,
  reading: null,
  acquiringSince: null,
  samples: [],
} satisfies Partial<MonitorState>

function clearBadReply(state: MonitorState): MonitorState {
  return state.error?.code === BAD_REPLY.code ? { ...state, error: null } : state
}

function applyMessage(state: MonitorState, action: Extract<MonitorAction, { type: "message" }>): MonitorState {
  const { message } = action
  if (message.type === "frame") {
    return { ...state, scene: message, latestT: message.t }
  }
  if (message.type === "pulse") {
    return { ...state, samples: message.samples }
  }
  const stillAcquiring = state.reading?.state === "acquiring" && state.acquiringSince !== null
  const acquiringSince = message.state === "acquiring" ? (stillAcquiring ? state.acquiringSince : message.t) : null
  return { ...state, reading: message, acquiringSince }
}

export function monitorReducer(state: MonitorState, action: MonitorAction): MonitorState {
  switch (action.type) {
    case "start":
      return { ...initialMonitorState, phase: "starting" }
    case "running":
      return { ...state, phase: "running" }
    case "ended":
      return { ...initialMonitorState, error: action.error }
    case "link":
      if (action.status === "live") {
        return { ...state, ...CLEARED_READINGS, link: "live", error: null }
      }
      if (action.status === "unreachable") {
        return { ...state, ...CLEARED_READINGS, link: "unreachable", error: SOCKET_UNAVAILABLE }
      }
      if (action.status === "connecting" && (state.link === "unreachable" || state.link === "busy")) {
        return state
      }
      return { ...state, link: action.status }
    case "message":
      return applyMessage(clearBadReply(state), action)
    case "notice":
      return { ...clearBadReply(state), notice: { ...action.error, id: (state.notice?.id ?? 0) + 1 } }
    case "unreadable":
      return state.error === null ? { ...state, error: BAD_REPLY } : state
    case "notice-expired":
      return state.notice?.id === action.id ? { ...state, notice: null } : state
  }
}
