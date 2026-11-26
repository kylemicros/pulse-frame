export const SETUP_MIN_FACE_SPAN_PX = 120
export const SETUP_BRIGHTNESS_MIN = 48
export const SETUP_BRIGHTNESS_MAX = 225
export const SETUP_NEAR_WHITE = 240
export const SETUP_BACKLIGHT_SHARE = 0.3
export const SETUP_MIN_FPS = 20
export const SETUP_PROMPT_HOLD_MS = 2000
export const SETUP_ALL_GOOD_MS = 3000
export const SETUP_START_ANYWAY_MS = 15000

const SPEED_WINDOW_MS = 1000
const RING_MARGIN_BOXES = 2
const LUMA_RED = 0.299
const LUMA_GREEN = 0.587
const LUMA_BLUE = 0.114
const RGBA = 4

export type SetupProblem = "noFace" | "far" | "behind" | "dark" | "bright" | "slow" | "moving"

export type SetupPrompt = SetupProblem | "allGood"

export type SetupRow = "distance" | "light" | "stillness" | "speed"

export type FaceBox = { left: number; top: number; right: number; bottom: number }

export type FrameLight = { brightness: number; backlitShare: number }

export type SetupSample = { face: boolean; spanPx: number; moving: boolean; light: FrameLight | null }

export type SetupCheck = {
  startedAt: number
  sample: SetupSample | null
  firstSampleAt: number | null
  recent: readonly number[]
  shown: SetupPrompt | null
  shownAt: number
  goodSince: number | null
}

type Outline = readonly (readonly [number, number])[] | null

function clampUnit(value: number): number {
  return Math.min(1, Math.max(0, value))
}

export function faceBox(outlines: readonly Outline[]): FaceBox | null {
  const points = outlines.flatMap((outline) => outline ?? [])
  if (points.length === 0) {
    return null
  }
  const xs = points.map(([x]) => clampUnit(x))
  const ys = points.map(([, y]) => clampUnit(y))
  return { left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) }
}

export function lightIn(pixels: Uint8ClampedArray, width: number, height: number, box: FaceBox): FrameLight | null {
  const left = Math.floor(box.left * width)
  const right = Math.ceil(box.right * width)
  const top = Math.floor(box.top * height)
  const bottom = Math.ceil(box.bottom * height)
  const marginX = (right - left) * RING_MARGIN_BOXES
  const marginY = (bottom - top) * RING_MARGIN_BOXES
  let faceSum = 0
  let faceCount = 0
  let ringWhite = 0
  let ringCount = 0
  for (let y = Math.max(0, top - marginY); y < Math.min(height, bottom + marginY); y += 1) {
    for (let x = Math.max(0, left - marginX); x < Math.min(width, right + marginX); x += 1) {
      const at = (y * width + x) * RGBA
      const luma = LUMA_RED * pixels[at] + LUMA_GREEN * pixels[at + 1] + LUMA_BLUE * pixels[at + 2]
      if (x >= left && x < right && y >= top && y < bottom) {
        faceSum += luma
        faceCount += 1
      } else {
        ringCount += 1
        ringWhite += luma > SETUP_NEAR_WHITE ? 1 : 0
      }
    }
  }
  if (faceCount === 0) {
    return null
  }
  return { brightness: faceSum / faceCount, backlitShare: ringCount === 0 ? 0 : ringWhite / ringCount }
}

export function newSetupCheck(at: number): SetupCheck {
  return { startedAt: at, sample: null, firstSampleAt: null, recent: [], shown: null, shownAt: at, goodSince: null }
}

function speed(check: SetupCheck, at: number): "good" | "slow" | "unknown" {
  if (check.firstSampleAt === null || at - check.firstSampleAt < SPEED_WINDOW_MS) {
    return "unknown"
  }
  const replies = check.recent.filter((time) => time > at - SPEED_WINDOW_MS).length
  return (replies * 1000) / SPEED_WINDOW_MS >= SETUP_MIN_FPS ? "good" : "slow"
}

function lightProblem(light: FrameLight): SetupProblem | null {
  if (light.backlitShare > SETUP_BACKLIGHT_SHARE) {
    return "behind"
  }
  if (light.brightness < SETUP_BRIGHTNESS_MIN) {
    return "dark"
  }
  return light.brightness > SETUP_BRIGHTNESS_MAX ? "bright" : null
}

export function setupRows(check: SetupCheck, at: number): Record<SetupRow, boolean> {
  const { sample } = check
  const face = sample !== null && sample.face
  return {
    distance: face && sample.spanPx >= SETUP_MIN_FACE_SPAN_PX,
    light: face && (sample.light === null || lightProblem(sample.light) === null),
    stillness: sample !== null && !sample.moving,
    speed: speed(check, at) === "good",
  }
}

function firstProblem(check: SetupCheck, at: number): SetupProblem | null {
  const { sample } = check
  if (sample === null) {
    return null
  }
  if (!sample.face) {
    return "noFace"
  }
  if (sample.spanPx < SETUP_MIN_FACE_SPAN_PX) {
    return "far"
  }
  const light = sample.light === null ? null : lightProblem(sample.light)
  if (light !== null) {
    return light
  }
  if (speed(check, at) === "slow") {
    return "slow"
  }
  return sample.moving ? "moving" : null
}

export function advanceSetupCheck(check: SetupCheck, at: number): SetupCheck {
  const allGood = Object.values(setupRows(check, at)).every(Boolean)
  const wanted = firstProblem(check, at) ?? (allGood ? "allGood" : null)
  const goodSince = allGood ? (check.goodSince ?? at) : null
  const staleAllGood = check.shown === "allGood" && goodSince === null
  const free = check.shown === null || staleAllGood || at - check.shownAt >= SETUP_PROMPT_HOLD_MS
  if (wanted !== check.shown && free) {
    return { ...check, goodSince, shown: wanted, shownAt: at }
  }
  return goodSince === check.goodSince ? check : { ...check, goodSince }
}

export function restartSetupSpeed(check: SetupCheck): SetupCheck {
  return { ...check, firstSampleAt: null, recent: [] }
}

export function addSetupSample(check: SetupCheck, sample: SetupSample, at: number): SetupCheck {
  const recent = [...check.recent.filter((time) => time > at - SPEED_WINDOW_MS), at]
  return advanceSetupCheck({ ...check, sample, recent, firstSampleAt: check.firstSampleAt ?? at }, at)
}

export function setupPassed(check: SetupCheck, at: number): boolean {
  return check.goodSince !== null && at - check.goodSince >= SETUP_ALL_GOOD_MS
}
