import type { SetupCheck, SetupSample } from "@/features/guided-capture/lib/setup-check"
import type { AppError } from "@/lib/errors"
import type { BpmMessage, FrameMessage, HrvMessage, PulseSample, ServerMessage } from "@/lib/socket/messages"
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
  variation: HrvMessage | null
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
  | { type: "setup-sample"; sample: SetupSample }

export type MonitorAction = SessionEvent | { type: "start" } | { type: "notice-expired"; id: number }

export type RunStatus = "idle" | "starting" | "checking" | "running" | "done" | "stopped"

export type Stage = "get-comfy" | "warm-up" | "counted" | "result"

export type VariationKind = "beat-to-beat" | "overall"

export type LikelyRange = { low: number; high: number }

export type RunResult =
  | {
      kind: "reading"
      bpm: number
      likely: LikelyRange | null
      beatToBeatMs: number | null
      overallMs: number | null
    }
  | { kind: "none"; why: AppError }

export type GuidedState = {
  monitor: MonitorState
  status: RunStatus
  startedAt: number | null
  check: SetupCheck | null
  now: number
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
  | { type: "start-anyway"; at: number }
  | { type: "notice-expired"; id: number }
