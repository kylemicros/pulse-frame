import type { AppError } from "@/lib/errors"
import type { ErrorMessage } from "@/lib/socket/messages"

const KEEPS_GOING = "Nothing to do: the next frame is already on its way. If this keeps showing up, press Stop, then Start."

const FALLBACK_MESSAGE = "The backend flagged a problem with this turn but did not say what."
const FALLBACK_ACTION = "The next frame is already on its way. If this keeps showing up, press Stop, then Start."

const PAGE_TEXT: ReadonlyMap<string, Omit<AppError, "code">> = new Map([
  [
    "BAD_FRAME",
    {
      message: "The backend could not read one frame from the camera and skipped it.",
      action: KEEPS_GOING,
    },
  ],
  [
    "BAD_TIMESTAMP",
    {
      message: "One frame arrived with a clock reading the backend didn't trust, so it skipped it.",
      action: KEEPS_GOING,
    },
  ],
  [
    "FRAME_TOO_LARGE",
    {
      message: "One frame was too big for the backend, so it skipped it.",
      action: KEEPS_GOING,
    },
  ],
  [
    "RATE_LIMITED",
    {
      message: "Frames came in faster than the backend takes them, so it dropped one.",
      action: KEEPS_GOING,
    },
  ],
])

function orFallback(text: string, fallback: string): string {
  return text.trim() === "" ? fallback : text
}

export function wireErrorText(error: ErrorMessage): AppError {
  const own = PAGE_TEXT.get(error.code)
  if (own !== undefined) {
    return { code: error.code, ...own }
  }
  return {
    code: error.code,
    message: orFallback(error.message, FALLBACK_MESSAGE),
    action: orFallback(error.action, FALLBACK_ACTION),
  }
}
