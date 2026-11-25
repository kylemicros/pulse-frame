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
      <div key={kind} className={cn(boxed && "rounded-lg border border-(--ds-border) bg-(--ds-surface-2) px-4 py-3")}>
        <dt className={boxed ? "font-semibold" : "text-sm font-semibold"}>{VARIATION_LABEL[kind]}</dt>
        {value === null ? (
          <dd className={boxed ? "text-lg font-bold" : "font-bold"}>{emptyText}</dd>
        ) : (
          <dd>
            <span
              className={cn(
                "font-mono font-bold tabular-nums",
                boxed ? "text-[2.25rem] leading-[1.1]" : "text-[1.75rem] leading-tight",
              )}
            >
              {Math.round(value)}
            </span>
            <abbr
              title="milliseconds"
              className={cn("ml-1.5 font-mono font-bold text-(--ds-muted) no-underline", !boxed && "text-sm")}
            >
              ms
            </abbr>
          </dd>
        )}
        {windows === null ? null : <dd className="text-sm text-(--ds-muted)">{windows[kind]}</dd>}
      </div>
    )
  })
}
