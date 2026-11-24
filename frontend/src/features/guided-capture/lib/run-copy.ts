import type { Stage } from "@/features/guided-capture/types"
import type { AppError } from "@/lib/errors"

export const NO_READING_PULSE: AppError = {
  code: "NO_READING",
  message: "Your pulse never showed clearly enough to count.",
  action: "Face a window so the light is even, hold still, then press Start again.",
}

export const NO_READING_FACE: AppError = {
  code: "NO_READING",
  message: "Your face kept leaving the camera's view.",
  action: "Sit facing the camera and keep your face in view, then press Start again.",
}

export const PAGE_HIDDEN: AppError = {
  code: "PAGE_HIDDEN",
  message: "The page was hidden, so the run stopped.",
  action: "Keep this tab in front for the whole run, then press Start again.",
}

export const SOCKET_BUSY: AppError = {
  code: "SOCKET_BUSY",
  message: "The app is busy in another tab or window, so the run stopped.",
  action: "Close the other one, then press Start again.",
}

const SKIPPED_ACTION =
  "Nothing to do; the run carries on. If this keeps showing up, press Stop to end this run, then Start for a fresh one."

type Words = Omit<AppError, "code">

const PLAIN_WORDS: ReadonlyMap<string, Words> = new Map<string, Words>([
  [
    "SOCKET_UNAVAILABLE",
    {
      message: "Can't reach the pulse reader, so the run stopped.",
      action: "Check pulse-frame is running on this computer, then press Start again.",
    },
  ],
  [
    "MODEL_LOAD_FAILED",
    {
      message: "The pulse reader couldn't load the part that finds your face, so the run stopped.",
      action:
        "Restart pulse-frame on this computer, then press Start again. If it keeps happening, its face finder needs installing again.",
    },
  ],
  [
    "BACKEND_FAILED",
    {
      message: "The pulse reader tripped over its own feet, so the run stopped.",
      action: "Restart pulse-frame on this computer, then press Start again.",
    },
  ],
  [
    "MESSAGE_TOO_BIG",
    {
      message: "The pulse reader hung up because this page sent far too much at once. That's a bug in this page.",
      action: "Press Start again, and report it if it happens twice.",
    },
  ],
  [
    "BAD_REPLY",
    {
      message: "The pulse reader sent something this page can't read, so it was ignored. The numbers may stall.",
      action:
        "If they stop moving, press Stop to end this run, then Start for a fresh one. If it keeps happening, update pulse-frame and restart it.",
    },
  ],
  ["BAD_FRAME", { message: "A split second of video couldn't be read, so it was skipped.", action: SKIPPED_ACTION }],
  [
    "BAD_TIMESTAMP",
    {
      message: "A split second of video arrived with a time that didn't add up, so it was skipped.",
      action: SKIPPED_ACTION,
    },
  ],
  [
    "FRAME_TOO_LARGE",
    { message: "A split second of video was too big to read, so it was skipped.", action: SKIPPED_ACTION },
  ],
  [
    "RATE_LIMITED",
    {
      message: "Video came in faster than the pulse reader takes it, so a split second was dropped.",
      action: SKIPPED_ACTION,
    },
  ],
  [
    "CAMERA_DENIED",
    {
      message: "The browser said no to the camera, so there is nothing to read.",
      action: "Allow the camera for this page in the browser's site settings, then press Start again.",
    },
  ],
  [
    "CAMERA_IN_USE",
    {
      message: "The camera is there, but another app is sitting on it and won't share.",
      action: "Quit the other app that has the camera (a video call, Photo Booth), then press Start again.",
    },
  ],
  [
    "CAMERA_NOT_FOUND",
    {
      message: "No camera turned up, or none that can do what this page needs.",
      action: "Plug a camera in, give it a second to wake up, then press Start again.",
    },
  ],
  [
    "CAMERA_UNSUPPORTED",
    {
      message: "This browser won't share the camera here. Browsers only do that on a secure or local address.",
      action: "Open pulse-frame at its local address in an up to date browser, then press Start.",
    },
  ],
  [
    "CAMERA_PLAYBACK_FAILED",
    {
      message: "The camera switched on but the preview refused to play.",
      action: "Press Start again. If the preview stays blank, reload the page.",
    },
  ],
  [
    "CAMERA_LOST",
    {
      message: "The camera dropped out mid-run. It was unplugged, switched off or grabbed by another app.",
      action: "Check the camera is plugged in and free, then press Start again.",
    },
  ],
  [
    "START_FAILED",
    {
      message: "Starting the camera hit something this page didn't expect, so it stopped cleanly.",
      action: "Press Start again. If it keeps happening, reload the page.",
    },
  ],
  [
    "FRAME_CAPTURE_FAILED",
    {
      message: "Reading the camera's video failed, so the run stopped.",
      action: "Press Start again. If it keeps happening, reload the page.",
    },
  ],
  [PAGE_HIDDEN.code, PAGE_HIDDEN],
  [SOCKET_BUSY.code, SOCKET_BUSY],
])

const UNKNOWN_WIRE_CODE = { message: "The pulse reader flagged a problem but didn't say what.", action: SKIPPED_ACTION }

export function plainError(error: AppError): AppError {
  const words = PLAIN_WORDS.get(error.code) ?? UNKNOWN_WIRE_CODE
  return { code: error.code, message: words.message, action: words.action }
}

const CAMERA_OFF_AFTER: ReadonlyMap<string, string> = new Map([
  ["CAMERA_DENIED", "The browser said no."],
  ["CAMERA_IN_USE", "Another app has it."],
  ["CAMERA_NOT_FOUND", "No camera found."],
  ["CAMERA_UNSUPPORTED", "This browser won't share it here."],
  ["CAMERA_PLAYBACK_FAILED", "The preview wouldn't play."],
  ["CAMERA_LOST", "It dropped out."],
  ["START_FAILED", "Something went sideways."],
  ["FRAME_CAPTURE_FAILED", "Something went sideways."],
])

export function cameraOffAfter(error: AppError): string {
  return `Camera's off. ${CAMERA_OFF_AFTER.get(error.code) ?? "The run stopped."}`
}

export const CAMERA_OFF_STOPPED = "Camera's off. Run stopped."

export const RUN_STOPPED_TEXT = "Run stopped. Press Start again for a fresh run."

export const DISCLAIMER =
  "For wellness and curiosity only. pulse-frame is not a medical device, and its numbers are estimates."

export const VARIATION_LATER = "Both variation numbers fill in with a later update."

export const NOT_ENOUGH_BEATS = "Not enough beats yet"

export const LIVE_WINDOW_TEXT = "Last 20 s"

export const PHASE_LINE: Record<Stage, string> = {
  "get-comfy": "Step 1 of 4, get comfy",
  "warm-up": "Step 2 of 4, warm-up",
  counted: "Step 3 of 4, counted",
  result: "Step 4 of 4, result",
}

export const CAMERA_CUE: Record<Stage, string> = {
  "get-comfy": "Face a window so the light is even.",
  "warm-up": "Keep your face in the oval. Look wherever you like.",
  counted: "Hold still. Shoulders loose, hands in your lap.",
  result: "You can move now. Stretch, even.",
}

export const CAMERA_OFF_DONE = "Camera's off. Run finished."

export const WATCH_TIP =
  "Checking against a watch? Open its history and read its average for the last minute of the run, the same window as the heart rate here."
