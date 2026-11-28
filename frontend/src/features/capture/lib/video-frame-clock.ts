type FrameTimes = Partial<Pick<VideoFrameCallbackMetadata, "captureTime" | "expectedDisplayTime">>

export class VideoFrameClock {
  private readonly video: HTMLVideoElement
  private readonly onFrame: (frameMs: number) => void
  private handle: number | null = null
  private offsetMs: number | null = null
  private running = false

  constructor(video: HTMLVideoElement, onFrame: (frameMs: number) => void) {
    this.video = video
    this.onFrame = onFrame
  }

  supported(): boolean {
    return "requestVideoFrameCallback" in this.video
  }

  start(): void {
    if (this.running || !this.supported()) {
      return
    }
    this.running = true
    this.request()
  }

  stop(): void {
    this.running = false
    if (this.handle !== null) {
      this.video.cancelVideoFrameCallback(this.handle)
      this.handle = null
    }
  }

  private request(): void {
    this.handle = this.video.requestVideoFrameCallback((now, metadata) => this.delivered(now, metadata))
  }

  private delivered(now: number, metadata: VideoFrameCallbackMetadata): void {
    const offsetMs = performance.now() - now
    this.handle = null
    if (!this.running) {
      return
    }
    this.offsetMs = this.offsetMs === null ? offsetMs : Math.min(this.offsetMs, offsetMs)
    const times: FrameTimes = metadata
    this.request()
    this.onFrame((times.captureTime ?? times.expectedDisplayTime ?? now) + this.offsetMs)
  }
}
