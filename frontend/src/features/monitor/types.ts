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
