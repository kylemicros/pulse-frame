import { memo } from "react"
import { PulseChart } from "@/features/monitor/components/pulse-chart"
import { pulseEmptyText } from "@/features/monitor/lib/empty-copy"
import type { Phase } from "@/features/monitor/types"
import type { PulseSample } from "@/lib/socket/messages"

type PulsePanelProps = {
  phase: Phase
  samples: readonly PulseSample[]
}

function PulsePanelView({ phase, samples }: PulsePanelProps) {
  return (
    <section aria-label="Pulse waveform" className="flex flex-col gap-2 border border-border p-4">
      <h2 className="text-sm font-medium text-muted-foreground">Pulse, last 20 s</h2>
      {samples.length === 0 ? null : <p className="sr-only">{`Waveform of the last ${samples.length} pulse samples.`}</p>}
      <div className="relative">
        <PulseChart samples={samples} className="aspect-auto h-40 w-full text-rose-500" />
        {samples.length === 0 ? (
          <p
            data-testid="pulse-empty"
            className="pointer-events-none absolute inset-0 flex items-center justify-center p-4 text-center text-sm text-muted-foreground"
          >
            {pulseEmptyText(phase)}
          </p>
        ) : null}
      </div>
    </section>
  )
}

export const PulsePanel = memo(PulsePanelView)
