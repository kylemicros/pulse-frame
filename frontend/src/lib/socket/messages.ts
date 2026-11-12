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

export type ServerMessage = FrameMessage | PulseMessage | BpmMessage | ErrorMessage

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

function isError(value: Fields): boolean {
  return typeof value.code === "string" && typeof value.message === "string" && typeof value.action === "string"
}

const CHECKS: Record<ServerMessage["type"], (value: Fields) => boolean> = {
  frame: isFrame,
  pulse: isPulse,
  bpm: isBpm,
  error: isError,
}

function isMessageType(value: unknown): value is ServerMessage["type"] {
  return value === "frame" || value === "pulse" || value === "bpm" || value === "error"
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
