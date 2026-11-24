import type { MonitorState, SessionEvent } from "@/features/monitor"
import type { AppError } from "@/lib/errors"

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
