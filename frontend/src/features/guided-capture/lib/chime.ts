const CHIME_HZ = 880
const CHIME_PEAK_GAIN = 0.15
const CHIME_RISE_S = 0.02
const CHIME_LENGTH_S = 0.4

function newContext(): AudioContext | null {
  try {
    return new AudioContext()
  } catch {
    return null
  }
}

export class Chime {
  private context: AudioContext | null = null

  prepare(): void {
    this.context ??= newContext()
  }

  play(then: "keep" | "close" = "keep"): void {
    const context = this.context
    if (context === null) {
      return
    }
    try {
      const now = context.currentTime
      const tone = new OscillatorNode(context, { type: "sine", frequency: CHIME_HZ })
      const level = new GainNode(context, { gain: 0 })
      level.gain.setValueAtTime(0, now)
      level.gain.linearRampToValueAtTime(CHIME_PEAK_GAIN, now + CHIME_RISE_S)
      level.gain.exponentialRampToValueAtTime(0.0001, now + CHIME_LENGTH_S)
      tone.connect(level).connect(context.destination)
      if (then === "close") {
        tone.addEventListener("ended", () => this.closeIf(context), { once: true })
      }
      tone.start(now)
      tone.stop(now + CHIME_LENGTH_S)
    } catch {
      this.close()
    }
  }

  close(): void {
    const context = this.context
    this.context = null
    if (context !== null) {
      void Chime.shut(context)
    }
  }

  private closeIf(context: AudioContext): void {
    if (this.context === context) {
      this.close()
    }
  }

  private static async shut(context: AudioContext): Promise<void> {
    try {
      await context.close()
    } catch {
      return
    }
  }
}
