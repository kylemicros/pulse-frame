import type { AppError } from "@/lib/errors"

export const CAMERA_DENIED: AppError = {
  code: "CAMERA_DENIED",
  message: "The browser said no to the camera, so there is nothing to read.",
  action: "Allow the camera for this page in the browser's site settings, then press Start again.",
}

export const CAMERA_IN_USE: AppError = {
  code: "CAMERA_IN_USE",
  message: "The camera is there, but another app is sitting on it and won't share.",
  action: "Quit the other app that has the camera (a video call, Photo Booth), then press Start again.",
}

export const CAMERA_NOT_FOUND: AppError = {
  code: "CAMERA_NOT_FOUND",
  message: "No camera turned up, or none that can do the job this page asks for.",
  action: "Plug a camera in, give it a second to wake up, then press Start again.",
}

export const CAMERA_UNSUPPORTED: AppError = {
  code: "CAMERA_UNSUPPORTED",
  message: "This page has no camera access here. Browsers only hand it out on a secure or local address.",
  action: "Open the page at http://127.0.0.1:4173 in a current browser, then press Start.",
}

export const CAMERA_PLAYBACK_FAILED: AppError = {
  code: "CAMERA_PLAYBACK_FAILED",
  message: "The camera switched on but the preview refused to play.",
  action: "Press Start again. If the preview stays black, reload the page.",
}

export const CAMERA_LOST: AppError = {
  code: "CAMERA_LOST",
  message: "The camera dropped out mid-session. It was unplugged, switched off or grabbed by another app.",
  action: "Check the camera is plugged in and free, then press Start again.",
}

export const START_FAILED: AppError = {
  code: "START_FAILED",
  message: "Starting the camera tripped over something this page did not expect, so it gave up cleanly.",
  action: "Press Start again. If it keeps happening, reload the page.",
}

export const FRAME_CAPTURE_FAILED: AppError = {
  code: "FRAME_CAPTURE_FAILED",
  message: "Grabbing a frame from the camera failed, so the stream stopped.",
  action: "Press Start again. If it keeps happening, reload the page.",
}

export class CameraUnsupportedError extends Error {
  constructor() {
    super("This page has no camera API.")
    this.name = "CameraUnsupportedError"
  }
}

const DENIED_NAMES = new Set(["NotAllowedError", "SecurityError"])
const IN_USE_NAMES = new Set(["NotReadableError", "AbortError"])
const NOT_FOUND_NAMES = new Set(["NotFoundError", "OverconstrainedError"])

function errorName(error: unknown): string | null {
  if (error instanceof Error || error instanceof DOMException) {
    return error.name
  }
  return null
}

export function cameraError(error: unknown): AppError {
  if (error instanceof CameraUnsupportedError) {
    return CAMERA_UNSUPPORTED
  }
  const name = errorName(error)
  if (name !== null && DENIED_NAMES.has(name)) {
    return CAMERA_DENIED
  }
  if (name !== null && IN_USE_NAMES.has(name)) {
    return CAMERA_IN_USE
  }
  if (name !== null && NOT_FOUND_NAMES.has(name)) {
    return CAMERA_NOT_FOUND
  }
  return START_FAILED
}
