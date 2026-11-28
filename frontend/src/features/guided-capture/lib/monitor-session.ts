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
  VideoFrameClock,
} from "@/features/capture"
import { plainError } from "@/features/guided-capture/lib/run-copy"
import {
  faceBox,
  lightIn,
  type FaceBox,
  type FrameLight,
  type SetupSample,
} from "@/features/guided-capture/lib/setup-check"
import type { SessionEvent } from "@/features/guided-capture/types"
import type { AppError } from "@/lib/errors"
import { PATCH_NAMES, type FrameMessage, type ServerMessage } from "@/lib/socket/messages"
import { FRAME_SPACING_MS, STREAM_URL, StreamClient } from "@/lib/socket/stream-client"

const VIDEO_NOT_READY_RETRY_MS = 50
const LIGHT_WIDTH = 160
const LIGHT_HEIGHT = 120

function createLightCanvas(): HTMLCanvasElement {
  const canvas = document.createElement("canvas")
  canvas.width = LIGHT_WIDTH
  canvas.height = LIGHT_HEIGHT
  return canvas
}

export class MonitorSession {
  private readonly video: HTMLVideoElement
  private readonly emit: (event: SessionEvent) => void
  private readonly canvas: HTMLCanvasElement = createFrameCanvas()
  private readonly lightCanvas: HTMLCanvasElement = createLightCanvas()
  private readonly lightContext = this.lightCanvas.getContext("2d", { willReadFrequently: true })
  private checking = true
  private stream: MediaStream | null = null
  private client: StreamClient | null = null
  private ended = false
  private scheduled = false
  private inFlightT: number | null = null
  private nextStartMs = Number.NEGATIVE_INFINITY
  private lastSocketSendMs = Number.NEGATIVE_INFINITY
  private lastStampMs = Number.NEGATIVE_INFINITY
  private pumpTimer: number | undefined = undefined
  private holdTimer: number | undefined = undefined
  private readonly trackWatch = new AbortController()
  private readonly frameClock: VideoFrameClock

  constructor(video: HTMLVideoElement, emit: (event: SessionEvent) => void) {
    this.video = video
    this.emit = emit
    this.frameClock = new VideoFrameClock(video, (frameMs) => this.cameraFrame(frameMs))
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
    this.frameClock.start()
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
    this.endSetupCheck()
    globalThis.clearTimeout(this.pumpTimer)
    globalThis.clearTimeout(this.holdTimer)
    this.frameClock.stop()
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
    this.pump(0)
  }

  private receive(message: ServerMessage): void {
    if (message.type === "error") {
      this.emit({ type: "notice", error: plainError(message) })
      if (this.inFlightT !== null) {
        this.turnDone()
      }
      return
    }
    this.emit({ type: "message", message })
    if (message.type === "frame" && this.inFlightT !== null && message.t === this.inFlightT) {
      if (this.checking) {
        this.emit({ type: "setup-sample", sample: this.sampleOf(message) })
      }
      this.turnDone()
    }
  }

  endSetupCheck(): void {
    this.checking = false
    this.lightCanvas.width = 0
    this.lightCanvas.height = 0
  }

  private sampleOf(message: FrameMessage): SetupSample {
    const box = faceBox(PATCH_NAMES.map((name) => message.patches[name].outline))
    if (box === null) {
      return { face: false, spanPx: 0, moving: message.moving, light: null }
    }
    return {
      face: true,
      spanPx: (box.right - box.left) * this.canvas.width,
      moving: message.moving,
      light: this.lightOf(box),
    }
  }

  private lightOf(box: FaceBox): FrameLight | null {
    const context = this.lightContext
    if (context === null) {
      return null
    }
    try {
      context.drawImage(this.canvas, 0, 0, LIGHT_WIDTH, LIGHT_HEIGHT)
      return lightIn(context.getImageData(0, 0, LIGHT_WIDTH, LIGHT_HEIGHT).data, LIGHT_WIDTH, LIGHT_HEIGHT, box)
    } catch {
      return null
    }
  }

  private turnDone(): void {
    this.inFlightT = null
    this.pump(0)
  }

  private canStart(): boolean {
    return !this.ended && !this.scheduled && this.inFlightT === null && this.client !== null && this.client.isOpen()
  }

  private cameraFrame(frameMs: number): void {
    if (!this.canStart() || Math.floor(frameMs) <= Math.floor(this.lastStampMs)) {
      return
    }
    this.scheduled = true
    void this.sendFrame(frameMs, performance.now())
  }

  private pump(minimumWaitMs: number): void {
    if (this.frameClock.supported() || !this.canStart()) {
      return
    }
    this.scheduled = true
    const spacing = this.nextStartMs - performance.now()
    const wait = Math.max(minimumWaitMs, Math.ceil(spacing), 0)
    globalThis.clearTimeout(this.pumpTimer)
    this.pumpTimer = globalThis.setTimeout(() => this.sendTimedFrame(), wait)
  }

  private sendTimedFrame(): void {
    if (this.ended) {
      return
    }
    const startMs = performance.now()
    if (startMs < this.nextStartMs) {
      this.scheduled = false
      this.pump(0)
      return
    }
    void this.sendFrame(startMs, startMs)
  }

  private async sendFrame(captureMs: number, startMs: number): Promise<void> {
    let frame: ArrayBuffer | null
    try {
      frame = await encodeFrame(this.video, this.canvas, captureMs)
    } catch {
      if (!this.ended) {
        this.finish(FRAME_CAPTURE_FAILED)
      }
      return
    }
    if (this.ended) {
      return
    }
    if (frame === null) {
      this.scheduled = false
      this.pump(VIDEO_NOT_READY_RETRY_MS)
      return
    }
    this.deliver(frame, captureMs, startMs)
  }

  private deliver(frame: ArrayBuffer, captureMs: number, startMs: number): void {
    if (this.ended) {
      return
    }
    const holdMs = this.lastSocketSendMs + FRAME_SPACING_MS - performance.now()
    if (holdMs > 0) {
      this.holdTimer = globalThis.setTimeout(() => this.deliver(frame, captureMs, startMs), Math.ceil(holdMs))
      return
    }
    this.scheduled = false
    if (this.client === null || !this.client.send(frame)) {
      return
    }
    this.inFlightT = Math.floor(captureMs)
    this.lastStampMs = captureMs
    this.lastSocketSendMs = performance.now()
    this.nextStartMs = startMs + FRAME_SPACING_MS
  }
}
