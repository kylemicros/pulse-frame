import { cn } from "cn"
import { VARIATION_LABEL } from "@/features/guided-capture/lib/run-copy"
import type { VariationKind } from "@/features/guided-capture/types"

const KINDS: readonly VariationKind[] = ["beat-to-beat", "overall"]

type VariationTilesProps = {
  tile: "plain" | "boxed"
  values: Readonly<Record<VariationKind, number | null>>
  emptyText: string
  windows: Readonly<Record<VariationKind, string>> | null
}

export function VariationTiles({ tile, values, emptyText, windows }: VariationTilesProps) {
  const boxed = tile === "boxed"
  return KINDS.map((kind) => {
    const value = values[kind]
    return (
      <div
        key={kind}
        className={cn(boxed && "flex flex-col gap-1 rounded-lg border border-(--ds-border) bg-(--ds-surface-2) px-4 py-3")}
      >
        <dt className="text-sm font-semibold">{VARIATION_LABEL[kind]}</dt>
        {value === null ? (
          <dd className="font-bold">{emptyText}</dd>
        ) : (
          <dd>
            <span
              className={cn(
                "font-mono font-bold tabular-nums",
                boxed ? "text-[2rem] leading-[1.1] md:text-[2.75rem]" : "text-[1.75rem] leading-tight",
              )}
            >
              {Math.round(value)}
            </span>
            <abbr title="milliseconds" className="ml-1.5 font-mono text-sm font-bold text-(--ds-muted) no-underline">
              ms
            </abbr>
          </dd>
        )}
        {windows === null ? null : <dd className="text-sm text-(--ds-muted)">{windows[kind]}</dd>}
      </div>
    )
  })
}
