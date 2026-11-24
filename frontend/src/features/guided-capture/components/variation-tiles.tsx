import { cn } from "cn"
import { NOT_ENOUGH_BEATS } from "@/features/guided-capture/lib/run-copy"

const LABELS = ["Beat to beat variation", "Overall rhythm variation"] as const

type VariationTilesProps = {
  tile: "plain" | "boxed"
}

export function VariationTiles({ tile }: VariationTilesProps) {
  return LABELS.map((label) => (
    <div
      key={label}
      className={cn(tile === "boxed" && "rounded-lg border border-(--ds-border) bg-(--ds-surface-2) px-4 py-3")}
    >
      <dt className={tile === "boxed" ? "font-semibold" : "text-sm font-semibold"}>{label}</dt>
      <dd className={tile === "boxed" ? "text-lg font-bold" : "font-bold"}>{NOT_ENOUGH_BEATS}</dd>
    </div>
  ))
}
