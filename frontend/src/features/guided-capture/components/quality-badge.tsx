import { cn } from "cn"
import type { QualityBand } from "@/features/guided-capture/lib/quality-band"

const WORD: Record<QualityBand, string> = { weak: "Weak", fair: "Fair", good: "Good" }

const BARS_ON: Record<QualityBand, number> = { weak: 1, fair: 2, good: 3 }

const BARS = [
  { x: 1, y: 9, height: 4 },
  { x: 6.5, y: 5, height: 8 },
  { x: 12, y: 1, height: 12 },
] as const

type QualityBadgeProps = {
  band: QualityBand
}

export function QualityBadge({ band }: QualityBadgeProps) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-(--ds-edge) bg-(--ds-surface) px-2.5 py-0.5 font-bold">
      <svg viewBox="0 0 16 14" aria-hidden="true" focusable="false" className="h-3.5 w-4">
        {BARS.map((bar, index) => (
          <rect
            key={bar.x}
            x={bar.x}
            y={bar.y}
            width="3"
            height={bar.height}
            className={cn(index < BARS_ON[band] ? "fill-(--ds-text)" : "fill-none stroke-(--ds-edge)")}
          />
        ))}
      </svg>
      {WORD[band]}
    </span>
  )
}
