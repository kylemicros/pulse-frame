import {
  CAMERA_LOST,
  CAMERA_PLAYBACK_FAILED,
  cameraError,
  createFrameCanvas,
  encodeFrame,
  FRAME_CAPTURE_FAILED,
  openCamera,
  START_FAILED,
  stopCamera,
} from "@/features/capture"
import type { SessionEvent } from "@/features/monitor/types"
import type { AppError } from "@/lib/errors"
import type { ServerMessage } from "@/lib/socket/messages"
import { FRAME_SPACING_MS, STREAM_URL, StreamClient } from "@/lib/socket/stream-client"
import { wireErrorText } from "@/lib/socket/wire-errors"

const VIDEO_NOT_READY_RETRY_MS = 50

export class MonitorSession {
  private readonly video: HTMLVideoElement
  private readonly emit: (event: SessionEvent) => void
  private readonly canvas: HTMLCanvasElement = createFrameCanvas()
  private stream: MediaStream | null = null
  private client: StreamClient | null = null
  private ended = false
  private connection = 0
  private scheduled = false
  private inFlightT: number | null = null
  private lastSendMs = Number.NEGATIVE_INFINITY
  private pumpTimer: number | undefined = undefined
  private readonly trackWatch = new AbortController()

  constructor(video: HTMLVideoElement, emit: (event: SessionEvent) => void) {
    this.video = video
    this.emit = emit
  }

  async start(): Promise<void> {
    try {
      await this.startSteps()
    } catch {
      this.finish(START_FAILED)
    }
  }

  stop(): void {
    this.finish(null)
  }

  private async startSteps(): Promise<void> {
    let stream: MediaStream
    try {
      stream = await openCamera()
    } catch (error) {
      this.finish(cameraError(error))
      return
    }
    if (this.ended) {
      stopCamera(stream)
      return
    }
    this.stream = stream
    for (const track of stream.getVideoTracks()) {
      track.addEventListener("ended", () => this.finish(CAMERA_LOST), { signal: this.trackWatch.signal })
    }
    this.video.srcObject = stream
    try {
      await this.video.play()
    } catch {
      this.finish(CAMERA_PLAYBACK_FAILED)
      return
    }
    if (this.ended) {
      return
    }
    this.emit({ type: "running" })
    this.client = new StreamClient(STREAM_URL, {
      onOpen: () => this.opened(),
      onStatus: (status) => this.emit({ type: "link", status }),
      onMessage: (message) => this.receive(message),
      onUnreadable: () => this.emit({ type: "unreadable" }),
      onFatal: (error) => this.finish(error),
    })
    this.client.connect()
  }

  private finish(error: AppError | null): void {
    if (this.ended) {
      return
    }
    this.ended = true
    window.clearTimeout(this.pumpTimer)
    this.trackWatch.abort()
    this.client?.close()
    this.client = null
    if (this.stream !== null) {
      stopCamera(this.stream)
      this.stream = null
    }
    try {
      this.video.srcObject = null
    } catch {
      this.video.removeAttribute("src")
    }
    this.emit({ type: "ended", error })
  }

  private opened(): void {
    this.connection += 1
    this.scheduled = false
    this.inFlightT = null
    window.clearTimeout(this.pumpTimer)
    this.pump(0)
  }

  private receive(message: ServerMessage): void {
    if (message.type === "error") {
      this.emit({ type: "notice", error: wireErrorText(message) })
      if (this.inFlightT !== null) {
        this.turnDone()
      }
      return
    }
    this.emit({ type: "message", message })
    if (message.type === "frame" && this.inFlightT !== null && message.t === this.inFlightT) {
      this.turnDone()
    }
  }

  private turnDone(): void {
    this.inFlightT = null
    this.pump(0)
  }

  private pump(minimumWaitMs: number): void {
    if (this.ended || this.scheduled || this.inFlightT !== null || this.client === null || !this.client.isOpen()) {
      return
    }
    this.scheduled = true
    const connection = this.connection
    const spacing = this.lastSendMs + FRAME_SPACING_MS - performance.now()
    const wait = Math.max(minimumWaitMs, Math.ceil(spacing), 0)
    window.clearTimeout(this.pumpTimer)
    this.pumpTimer = window.setTimeout(() => void this.sendFrame(connection), wait)
  }

  private isStale(connection: number): boolean {
    return this.ended || connection !== this.connection
  }

  private async sendFrame(connection: number): Promise<void> {
    if (this.isStale(connection)) {
      return
    }
    const captureMs = performance.now()
    if (captureMs - this.lastSendMs < FRAME_SPACING_MS) {
      this.scheduled = false
      this.pump(0)
      return
    }
    let frame: ArrayBuffer | null
    try {
      frame = await encodeFrame(this.video, this.canvas, captureMs)
    } catch {
      if (!this.isStale(connection)) {
        this.finish(FRAME_CAPTURE_FAILED)
      }
      return
    }
    if (this.isStale(connection)) {
      return
    }
    this.scheduled = false
    if (frame === null) {
      this.pump(VIDEO_NOT_READY_RETRY_MS)
      return
    }
    if (this.client === null || !this.client.send(frame)) {
      return
    }
    this.inFlightT = Math.floor(captureMs)
    this.lastSendMs = performance.now()
  }
}
