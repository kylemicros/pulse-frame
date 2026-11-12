import { memo, useMemo } from "react"
import { Line, LineChart, XAxis, YAxis } from "recharts"
import { ChartContainer, type ChartConfig } from "@/components/ui/chart"
import { pulseEmptyText } from "@/features/monitor/lib/empty-copy"
import type { Phase } from "@/features/monitor/types"
import type { PulseSample } from "@/lib/socket/messages"

const PULSE_WINDOW_MS = 20000

const CHART_CONFIG = { value: { label: "Pulse" } } satisfies ChartConfig

type PulsePanelProps = {
  phase: Phase
  samples: readonly PulseSample[]
}

function PulsePanelView({ phase, samples }: PulsePanelProps) {
  const data = useMemo(() => samples.map(([t, value]) => ({ t, value })), [samples])
  const newest = data.at(-1)?.t
  const domain: [number, number] | ["dataMin", "dataMax"] =
    newest === undefined ? ["dataMin", "dataMax"] : [newest - PULSE_WINDOW_MS, newest]
  return (
    <section aria-label="Pulse waveform" className="flex flex-col gap-2 border border-border p-4">
      <h2 className="text-sm font-medium text-muted-foreground">Pulse, last 20 s</h2>
      {data.length === 0 ? null : <p className="sr-only">{`Waveform of the last ${data.length} pulse samples.`}</p>}
      <div className="relative">
        <ChartContainer config={CHART_CONFIG} className="aspect-auto h-40 w-full text-rose-500" aria-hidden="true">
          <LineChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }} accessibilityLayer={false}>
            <XAxis dataKey="t" type="number" domain={domain} allowDataOverflow hide />
            <YAxis domain={["auto", "auto"]} hide />
            <Line
              dataKey="value"
              type="linear"
              dot={false}
              stroke="currentColor"
              strokeWidth={2}
              isAnimationActive={false}
            />
          </LineChart>
        </ChartContainer>
        {data.length === 0 ? (
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
