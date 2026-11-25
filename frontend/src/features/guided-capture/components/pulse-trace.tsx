import { PULSE_WINDOW_MS, PulseChart } from "@/features/guided-capture/components/pulse-chart"
import type { PulseSample } from "@/lib/socket/messages"

const WINDOW_S = PULSE_WINDOW_MS / 1000

type PulseTraceProps = {
  samples: readonly PulseSample[]
}

function drawnSeconds(samples: readonly PulseSample[]): number {
  const first = samples.at(0)
  const last = samples.at(-1)
  if (first === undefined || last === undefined) {
    return 0
  }
  return Math.min(WINDOW_S, Math.round((last[0] - first[0]) / 1000))
}

function traceLabel(drawn: number): string {
  if (drawn === 0) {
    return `Pulse trace over the last ${WINDOW_S} seconds, nothing drawn yet.`
  }
  if (drawn < WINDOW_S) {
    return `Pulse trace over the last ${WINDOW_S} seconds, ${drawn} of ${WINDOW_S} seconds drawn so far.`
  }
  return `Pulse trace over the last ${WINDOW_S} seconds, drawn across the whole window.`
}

export function PulseTrace({ samples }: PulseTraceProps) {
  const drawn = drawnSeconds(samples)
  const filling = drawn < WINDOW_S
  return (
    <figure className="flex flex-col gap-1">
      <div className="flex justify-between gap-2 text-sm">
        <span>Pulse, last 20 s</span>
        {filling ? <span className="font-mono text-(--ds-muted)">{`Filling: ${drawn} of ${WINDOW_S} s`}</span> : null}
      </div>
      <div
        // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
        role="img"
        aria-label={traceLabel(drawn)}
        className="relative h-20 overflow-hidden rounded-md border border-(--ds-border) bg-(--ds-surface)"
      >
        {filling ? (
          <div
            aria-hidden="true"
            className="absolute inset-y-1 left-0.5 rounded-sm border border-dashed border-(--ds-edge) bg-(--ds-surface-2)"
            style={{ width: `${((WINDOW_S - drawn) / WINDOW_S) * 100}%` }}
          />
        ) : null}
        <PulseChart samples={samples} className="relative aspect-auto h-full w-full text-(--ds-count)" />
      </div>
      {filling ? (
        <figcaption className="text-sm text-(--ds-muted)">The outlined part fills in as the trace grows.</figcaption>
      ) : null}
    </figure>
  )
}
