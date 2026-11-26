import {
  backlightFits,
  brightnessFits,
  fpsFits,
  SETUP_BACKLIGHT_SHARE,
  SETUP_BRIGHTNESS_MAX,
  SETUP_BRIGHTNESS_MIN,
  SETUP_MIN_FACE_SPAN_PX,
  SETUP_MIN_FPS,
  spanFits,
  type SetupSample,
} from "@/features/guided-capture/lib/setup-check"
import type { CheckEnd } from "@/features/guided-capture/types"

export const CALIBRATE_FLAG = "calibrate"
export const READOUT_REDRAW_MS = 500
export const CLEAR_SHARE_FLOOR = 50

export const READOUT_HEADING = "Calibration"
export const READOUT_NOTE = "On for ?calibrate. Only on this screen; nothing is sent or stored."
export const READOUT_FOOT =
  "The first four are the last values before the warm-up. Clear share is how much of the counted part the pulse showed clearly."
export const READOUT_PHASE = { live: "Live, setup check", frozen: "This run" } as const
export const READOUT_COLUMNS = { measure: "Measure", live: "Now", frozen: "Value", limit: "Limit", check: "Check" } as const
export const READOUT_CHECK = { good: "Good", notYet: "Not yet" } as const

export type ReadoutCell = { text: string; good: boolean }

export type ReadoutRow = ReadoutCell & { label: string; limit: string }

const WAITING = "Waiting"
const NOT_MEASURED = "Not measured"
const PERCENT = 100
const GOOD_MARK = "+"
const NOT_YET_MARK = "-"

function cell(raw: number | null, good: (raw: number) => boolean, shown: (raw: number) => string, empty: string): ReadoutCell {
  return raw === null ? { text: empty, good: false } : { text: shown(raw), good: good(raw) }
}

function whole(raw: number): string {
  return String(Math.round(raw))
}

function percent(raw: number): string {
  return `${Math.round(raw)}%`
}

function shareAsPercent(share: number): string {
  return percent(share * PERCENT)
}

export function measureRows(sample: SetupSample | null, fps: number | null, frozen: boolean): ReadoutRow[] {
  const face = sample !== null && sample.face ? sample : null
  const light = face?.light ?? null
  const empty = frozen ? NOT_MEASURED : WAITING
  const lightEmpty = face === null ? empty : NOT_MEASURED
  const backlightMax = Math.round(SETUP_BACKLIGHT_SHARE * PERCENT)
  return [
    {
      label: "Face span (px)",
      limit: `at least ${SETUP_MIN_FACE_SPAN_PX}`,
      ...cell(face?.spanPx ?? null, spanFits, whole, empty),
    },
    {
      label: "Face brightness (0 to 255)",
      limit: `${SETUP_BRIGHTNESS_MIN} to ${SETUP_BRIGHTNESS_MAX}`,
      ...cell(light?.brightness ?? null, brightnessFits, whole, lightEmpty),
    },
    {
      label: "Backlight (% near white)",
      limit: `at most ${backlightMax}%`,
      ...cell(light?.backlitShare ?? null, backlightFits, shareAsPercent, lightEmpty),
    },
    {
      label: "Frames per second",
      limit: `at least ${SETUP_MIN_FPS}`,
      ...cell(fps, fpsFits, whole, empty),
    },
  ]
}

function shareInRange(clearPercent: number | null): number | null {
  const inRange = clearPercent !== null && Number.isFinite(clearPercent) && clearPercent >= 0 && clearPercent <= PERCENT
  return inRange ? clearPercent : null
}

export function clearShareRow(clearPercent: number | null): ReadoutRow {
  return {
    label: "Clear share (%)",
    limit: `at least ${CLEAR_SHARE_FLOOR}%`,
    ...cell(shareInRange(clearPercent), (raw) => Math.round(raw) >= CLEAR_SHARE_FLOOR, percent, NOT_MEASURED),
  }
}

export function heldKey(row: ReadoutCell): string {
  return `${row.good ? GOOD_MARK : NOT_YET_MARK}${row.text}`
}

export function fromHeldKey(key: string): ReadoutCell {
  return { text: key.slice(1), good: key.startsWith(GOOD_MARK) }
}

export function checkEndLine(checkEnd: CheckEnd): string {
  const how = checkEnd.how === "passed" ? "passed" : "started anyway"
  return `Setup check: ${how} after ${Math.round(checkEnd.tookMs / 1000)} s.`
}
