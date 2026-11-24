import { memo, useMemo } from "react"
import { Line, LineChart, XAxis, YAxis } from "recharts"
import { ChartContainer, type ChartConfig } from "@/components/ui/chart"
import type { PulseSample } from "@/lib/socket/messages"

export const PULSE_WINDOW_MS = 20000

const CHART_CONFIG = { value: { label: "Pulse" } } satisfies ChartConfig

type PulseChartProps = {
  samples: readonly PulseSample[]
  className: string
}

function PulseChartView({ samples, className }: PulseChartProps) {
  const data = useMemo(() => samples.map(([t, value]) => ({ t, value })), [samples])
  const newest = data.at(-1)?.t
  const domain: [number, number] | ["dataMin", "dataMax"] =
    newest === undefined ? ["dataMin", "dataMax"] : [newest - PULSE_WINDOW_MS, newest]
  return (
    <ChartContainer config={CHART_CONFIG} className={className} aria-hidden="true">
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
  )
}

export const PulseChart = memo(PulseChartView)
