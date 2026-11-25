export type PatchName = "forehead" | "left_cheek" | "right_cheek"

export const PATCH_NAMES: readonly PatchName[] = ["forehead", "left_cheek", "right_cheek"]

export type Point = readonly [number, number]

export type Patch = {
  usable: boolean
  outline: Point[] | null
}

export type FrameMessage = {
  type: "frame"
  t: number
  face: boolean
  moving: boolean
  patches: Record<PatchName, Patch>
}

export type PulseSample = readonly [number, number]

export type PulseMessage = {
  type: "pulse"
  samples: PulseSample[]
}

export type ReadingState = "acquiring" | "ok" | "low_quality"

export type BpmMessage = {
  type: "bpm"
  t: number
  bpm: number | null
  quality_db: number | null
  state: ReadingState
}

export type ErrorMessage = {
  type: "error"
  code: string
  message: string
  action: string
}

export type NoReadingCode = "SIGNAL_TOO_WEAK" | "READING_FLOOR_NOT_CLEARED"

export type NoReadingWhy = "face_left_view" | "faint_pulse"

export type HrvMessage = {
  type: "hrv"
  t: number
  rmssd_ms: number | null
  sdnn_ms: number | null
  minute_bpm: number | null
  minute_count: number
  bpm_low: number | null
  bpm_high: number | null
  no_reading: NoReadingCode | null
  why: NoReadingWhy | null
  clear_percent: number | null
}

export type ServerMessage = FrameMessage | PulseMessage | BpmMessage | HrvMessage | ErrorMessage

type Fields = Record<string, unknown>

function isFields(value: unknown): value is Fields {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function isNumberOrNull(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value)
}

function isPair(value: unknown): value is readonly [number, number] {
  return Array.isArray(value) && value.length === 2 && isFiniteNumber(value[0]) && isFiniteNumber(value[1])
}

function isPatch(value: unknown): value is Patch {
  if (!isFields(value) || typeof value.usable !== "boolean") {
    return false
  }
  if (value.outline === null) {
    return !value.usable
  }
  return value.usable && Array.isArray(value.outline) && value.outline.every(isPair)
}

function isFrame(value: Fields): boolean {
  const patches = value.patches
  return (
    isFiniteNumber(value.t) &&
    typeof value.face === "boolean" &&
    typeof value.moving === "boolean" &&
    isFields(patches) &&
    PATCH_NAMES.every((name) => isPatch(patches[name]))
  )
}

function isPulse(value: Fields): boolean {
  return Array.isArray(value.samples) && value.samples.every(isPair)
}

function isBpm(value: Fields): boolean {
  return (
    isFiniteNumber(value.t) &&
    isNumberOrNull(value.bpm) &&
    isNumberOrNull(value.quality_db) &&
    (value.state === "acquiring" || value.state === "ok" || value.state === "low_quality")
  )
}

const HRV_NUMBERS = ["rmssd_ms", "sdnn_ms", "minute_bpm", "bpm_low", "bpm_high", "clear_percent"] as const

function hasHrvNoReading(value: Fields): boolean {
  const { no_reading: code, why } = value
  if ((value.clear_percent !== null) !== (why === "faint_pulse")) {
    return false
  }
  if (code === null) {
    return why === null
  }
  if (value.minute_bpm !== null) {
    return false
  }
  if (code === "SIGNAL_TOO_WEAK") {
    return why === null
  }
  return code === "READING_FLOOR_NOT_CLEARED" && (why === "face_left_view" || why === "faint_pulse")
}

function isHrv(value: Fields): boolean {
  return (
    isFiniteNumber(value.t) &&
    isFiniteNumber(value.minute_count) &&
    Number.isInteger(value.minute_count) &&
    value.minute_count >= 0 &&
    HRV_NUMBERS.every((key) => isNumberOrNull(value[key])) &&
    hasHrvNoReading(value)
  )
}

function isError(value: Fields): boolean {
  return typeof value.code === "string" && typeof value.message === "string" && typeof value.action === "string"
}

const CHECKS: Record<ServerMessage["type"], (value: Fields) => boolean> = {
  frame: isFrame,
  pulse: isPulse,
  bpm: isBpm,
  hrv: isHrv,
  error: isError,
}

function isMessageType(value: unknown): value is ServerMessage["type"] {
  return typeof value === "string" && Object.hasOwn(CHECKS, value)
}

function isServerMessage(value: unknown): value is ServerMessage {
  return isFields(value) && isMessageType(value.type) && CHECKS[value.type](value)
}

export function parseServerMessage(text: string): ServerMessage | null {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return null
  }
  return isServerMessage(value) ? value : null
}
