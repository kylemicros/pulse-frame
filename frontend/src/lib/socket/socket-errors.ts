import type { AppError } from "@/lib/errors"

export const SOCKET_UNAVAILABLE: AppError = {
  code: "SOCKET_UNAVAILABLE",
  message: "Can't reach the backend at 127.0.0.1:8000. Either it is not running or it turned this page away.",
  action:
    "Start it from backend/ with uv run python -m pulse_frame.stream. If the backend is already running, open this page at http://127.0.0.1:4173 (or http://127.0.0.1:5173 with pnpm dev). The page keeps knocking on its own.",
}

export const MODEL_LOAD_FAILED: AppError = {
  code: "MODEL_LOAD_FAILED",
  message: "The backend could not load its face model, so it can't read anything.",
  action:
    "Check the backend terminal for the error code, fetch the model again from backend/ with uv run python -m pulse_frame.vision.model, restart the backend, then press Start.",
}

export const BACKEND_FAILED: AppError = {
  code: "BACKEND_FAILED",
  message: "The backend tripped over its own feet and dropped the stream.",
  action: "Check the backend's terminal for the error, restart it, then press Start.",
}

export const MESSAGE_TOO_BIG: AppError = {
  code: "MESSAGE_TOO_BIG",
  message: "The backend hung up because a frame was far too big. That is a bug in this page.",
  action: "Press Start to try again, and report it if it happens twice.",
}

export const BAD_REPLY: AppError = {
  code: "BAD_REPLY",
  message: "The backend sent something this page can't make sense of, so it was ignored. The stream may have stalled.",
  action:
    "Press Stop, then Start. If it happens again, pull the latest code, rebuild the page and restart the backend so both sides match.",
}
