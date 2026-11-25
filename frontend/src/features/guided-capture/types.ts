import type { AppError } from "@/lib/errors"
import type { BpmMessage, FrameMessage, PulseSample, ServerMessage } from "@/lib/socket/messages"
import type { LinkStatus } from "@/lib/socket/stream-client"

export type Phase = "idle" | "starting" | "running"

export type Notice = AppError & { id: number }

export type MonitorState = {
  phase: Phase
  link: LinkStatus | null
  scene: FrameMessage | null
  latestT: number | null
  reading: BpmMessage | null
  acquiringSince: number | null
  samples: readonly PulseSample[]
  error: AppError | null
  notice: Notice | null
}

export type SessionEvent =
  | { type: "running" }
  | { type: "ended"; error: AppError | null }
  | { type: "link"; status: LinkStatus }
  | { type: "message"; message: Exclude<ServerMessage, { type: "error" }> }
  | { type: "notice"; error: AppError }
  | { type: "unreadable" }

export type MonitorAction = SessionEvent | { type: "start" } | { type: "notice-expired"; id: number }

export type RunStatus = "idle" | "starting" | "running" | "done" | "stopped"

export type Stage = "get-comfy" | "warm-up" | "counted" | "result"

export type RunResult = { kind: "reading"; bpm: number } | { kind: "none"; why: AppError }

export type WindowTotals = {
  okMs: number
  bpmMs: number
  noFaceMs: number
}

export type GuidedState = {
  monitor: MonitorState
  status: RunStatus
  startedAt: number | null
  now: number
  totals: WindowTotals
  result: RunResult | null
  lastGoodBpm: number | null
  haltError: AppError | null
  endError: AppError | null
}

export type GuidedAction =
  | { type: "start" }
  | { type: "session"; event: SessionEvent; at: number }
  | { type: "tick"; at: number }
  | { type: "halt"; error: AppError }
  | { type: "notice-expired"; id: number }
