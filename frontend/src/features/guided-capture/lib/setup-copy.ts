import {
  SETUP_ALL_GOOD_MS,
  type SetupCheck,
  type SetupProblem,
  type SetupRow,
} from "@/features/guided-capture/lib/setup-check"

export const SETUP_PROMPTS: Record<SetupProblem, { prompt: string; line: string }> = {
  noFace: { prompt: "Can't find your face.", line: "Sit facing the camera so your whole face fits in the oval." },
  far: {
    prompt: "Move closer to the camera.",
    line: "You're a bit far away to read. Scoot in until your face fills the oval.",
  },
  behind: {
    prompt: "There is light behind you.",
    line: "A bright window or lamp behind you turns your face into a silhouette. Turn so the light hits your face instead.",
  },
  dark: {
    prompt: "Make the room a little brighter.",
    line: "Your face is hiding in the shadows. Switch on a lamp or face a window.",
  },
  bright: {
    prompt: "Ease off the light a little.",
    line: "Your face is washed out. Back away from the lamp or point it somewhere else.",
  },
  slow: {
    prompt: "The camera is running slow.",
    line: "Close other apps using the camera, and add some light. Cameras slow down in the dark.",
  },
  moving: {
    prompt: "Hold still.",
    line: "Settle in, then stay put like a statue for a few seconds. Breathing is allowed.",
  },
}

export const ALL_GOOD_PROMPT = "All good. Hold that."

export function setupPromptText(check: SetupCheck): string | null {
  if (check.shown === null) {
    return null
  }
  return check.shown === "allGood" ? ALL_GOOD_PROMPT : SETUP_PROMPTS[check.shown].prompt
}

export function allGoodLine(seconds: number): string {
  return `Warm-up starts in ${seconds} s. Stay just like that.`
}

export const ALL_GOOD_SAID = `All good. Warm-up starts in ${SETUP_ALL_GOOD_MS / 1000} seconds.`

export const SETUP_ROWS: readonly { row: SetupRow; name: string }[] = [
  { row: "distance", name: "Distance" },
  { row: "light", name: "Light" },
  { row: "stillness", name: "Stillness" },
  { row: "speed", name: "Camera speed" },
]

export const SETUP_LEAD = "Sit how you'll sit for the run. When all four say Good, the warm-up starts by itself."

export const START_ANYWAY_READY = "Can't fix it right now? You can start anyway. The reading may come out weaker."

export const START_ANYWAY_SAID = "You can start anyway now."

export function startAnywayIn(seconds: number): string {
  return `Can't fix it right now? Start anyway shows up in ${seconds} s.`
}

export function secondsToGo(seconds: number): string {
  return seconds === 1 ? "1 second to go" : `${seconds} seconds to go`
}
