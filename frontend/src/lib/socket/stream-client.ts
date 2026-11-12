import type { AppError } from "@/lib/errors"
import { retryDelay } from "@/lib/socket/backoff"
import { parseServerMessage, type ServerMessage } from "@/lib/socket/messages"
import { BACKEND_FAILED, MESSAGE_TOO_BIG, MODEL_LOAD_FAILED } from "@/lib/socket/socket-errors"

export const STREAM_URL = "ws://127.0.0.1:8000/ws/stream"

export const FRAME_SPACING_MS = 34

export type LinkStatus = "connecting" | "live" | "busy" | "unreachable"

export type StreamClientEvents = {
  onOpen: () => void
  onStatus: (status: LinkStatus) => void
  onMessage: (message: ServerMessage) => void
  onUnreadable: () => void
  onFatal: (error: AppError) => void
}

const CLOSE_NORMAL = 1000
const CLOSE_MESSAGE_TOO_BIG = 1009
const CLOSE_INTERNAL_ERROR = 1011
const CLOSE_TRY_AGAIN_LATER = 1013

export class StreamClient {
  private readonly url: string
  private readonly events: StreamClientEvents
  private socket: WebSocket | null = null
  private attempt = 0
  private live = false
  private closed = false
  private retryTimer: number | undefined = undefined

  constructor(url: string, events: StreamClientEvents) {
    this.url = url
    this.events = events
  }

  connect(): void {
    if (this.closed) {
      return
    }
    this.retryTimer = undefined
    this.live = false
    this.events.onStatus("connecting")
    let socket: WebSocket
    try {
      socket = new WebSocket(this.url)
    } catch {
      this.retry("unreachable")
      return
    }
    socket.binaryType = "arraybuffer"
    socket.addEventListener("open", () => {
      if (this.socket === socket) {
        this.events.onOpen()
      }
    })
    socket.addEventListener("message", (event: MessageEvent<unknown>) => this.receive(socket, event))
    socket.addEventListener("close", (event) => this.handleClose(socket, event))
    this.socket = socket
  }

  isOpen(): boolean {
    return this.socket !== null && this.socket.readyState === WebSocket.OPEN
  }

  send(frame: ArrayBuffer): boolean {
    if (this.socket === null || this.socket.readyState !== WebSocket.OPEN) {
      return false
    }
    this.socket.send(frame)
    return true
  }

  close(): void {
    this.closed = true
    window.clearTimeout(this.retryTimer)
    this.retryTimer = undefined
    const socket = this.socket
    this.socket = null
    if (socket !== null && socket.readyState !== WebSocket.CLOSED) {
      socket.close(CLOSE_NORMAL, "stopped")
    }
  }

  private receive(socket: WebSocket, event: MessageEvent<unknown>): void {
    if (this.socket !== socket || this.closed) {
      return
    }
    if (!this.live) {
      this.live = true
      this.attempt = 0
      this.events.onStatus("live")
    }
    const message = typeof event.data === "string" ? parseServerMessage(event.data) : null
    if (message === null) {
      this.events.onUnreadable()
      return
    }
    this.events.onMessage(message)
  }

  private handleClose(socket: WebSocket, event: CloseEvent): void {
    if (this.socket !== socket || this.closed) {
      return
    }
    this.socket = null
    if (event.code === CLOSE_INTERNAL_ERROR) {
      this.fail(event.reason === MODEL_LOAD_FAILED.code ? MODEL_LOAD_FAILED : BACKEND_FAILED)
      return
    }
    if (event.code === CLOSE_MESSAGE_TOO_BIG) {
      this.fail(MESSAGE_TOO_BIG)
      return
    }
    this.retry(event.code === CLOSE_TRY_AGAIN_LATER ? "busy" : "unreachable")
  }

  private fail(error: AppError): void {
    this.closed = true
    this.events.onFatal(error)
  }

  private retry(status: "busy" | "unreachable"): void {
    this.events.onStatus(status)
    const delay = retryDelay(this.attempt)
    this.attempt += 1
    this.retryTimer = window.setTimeout(() => this.connect(), delay)
  }
}
