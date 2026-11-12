import { Badge } from "@/components/ui/badge"
import { NO_QUALITY_YET } from "@/features/monitor/lib/empty-copy"
import { qualityBand } from "@/features/monitor/lib/quality-band"

type QualityPanelProps = {
  qualityDb: number | null
}

export function QualityPanel({ qualityDb }: QualityPanelProps) {
  return (
    <section aria-label="Signal quality" className="flex flex-col gap-2 border border-border p-4">
      <h2 className="text-sm font-medium text-muted-foreground">Signal quality</h2>
      {qualityDb === null ? (
        <p className="text-sm text-muted-foreground">{NO_QUALITY_YET}</p>
      ) : (
        <p className="flex items-center gap-3">
          <span className="text-2xl font-semibold tabular-nums text-foreground">{qualityDb.toFixed(2)} dB</span>
          <Badge variant="outline">{qualityBand(qualityDb)}</Badge>
        </p>
      )}
    </section>
  )
}
