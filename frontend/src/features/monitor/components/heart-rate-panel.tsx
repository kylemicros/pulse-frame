import { cn } from "cn"
import { useHeldValue } from "@/features/monitor/hooks/use-held-value"
import { useShownBpm } from "@/features/monitor/hooks/use-shown-bpm"
import { DASH_REASON, sceneHint, settlingSeconds } from "@/features/monitor/lib/reading-copy"
import type { Phase } from "@/features/monitor/types"
import type { BpmMessage, FrameMessage } from "@/lib/socket/messages"

const DASH = "-"

type HeartRatePanelProps = {
  phase: Phase
  reading: BpmMessage | null
  scene: FrameMessage | null
  latestT: number | null
  acquiringSince: number | null
}

function caption(props: HeartRatePanelProps, reason: string): string {
  const { phase, reading, latestT, acquiringSince } = props
  if (phase === "idle") {
    return "Press Start and look at the camera."
  }
  if (reading === null) {
    return "Waiting for the first reading."
  }
  if (reading.state === "acquiring") {
    return `Settling ${settlingSeconds(acquiringSince ?? reading.t, latestT)} s`
  }
  if (reading.state === "ok") {
    return "Beats per minute"
  }
  return reason
}

export function HeartRatePanel(props: HeartRatePanelProps) {
  const shown = useShownBpm(props.reading)
  const reason = DASH_REASON[useHeldValue(sceneHint(props.scene))]
  const text = shown.value === null ? DASH : String(Math.round(shown.value))
  const spoken = shown.value === null ? "No reading" : `${text} beats per minute`
  return (
    <section aria-label="Heart rate" className="flex flex-col gap-2 border border-border p-4">
      <h2 className="text-sm font-medium text-muted-foreground">Heart rate</h2>
      <p className="flex items-baseline gap-2">
        <span
          data-testid="bpm-value"
          aria-hidden="true"
          className={cn("text-6xl font-semibold tabular-nums text-foreground", shown.dimmed && "opacity-40")}
        >
          {text}
        </span>
        <span className="sr-only">{spoken}</span>
        <span aria-hidden="true" className="text-sm text-muted-foreground">
          BPM
        </span>
      </p>
      <p className="text-sm text-muted-foreground">{caption(props, reason)}</p>
    </section>
  )
}
