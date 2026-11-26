import { cn } from "cn"
import { TableCell, TableHead, TableRow } from "@/components/ui/table"
import { useHeldValue } from "@/features/guided-capture/hooks/use-held-value"
import {
  fromHeldKey,
  heldKey,
  READOUT_CHECK,
  READOUT_REDRAW_MS,
  type ReadoutRow,
} from "@/features/guided-capture/lib/calibration-readout"

const CELL = "h-auto px-1.5 py-1 align-top border-b border-(--ds-border) @max-[360px]:border-0 @max-[360px]:p-0"
const SUM_CELL = "border-t-2 border-t-(--ds-edge)"

type CalibrationReadoutRowProps = {
  row: ReadoutRow
  live: boolean
  sum?: boolean
}

export function CalibrationReadoutRow({ row, live, sum = false }: CalibrationReadoutRowProps) {
  const held = fromHeldKey(useHeldValue(heldKey(row), READOUT_REDRAW_MS))
  const { text, good } = live ? held : row
  const cell = cn(CELL, sum && SUM_CELL)
  return (
    <TableRow
      className={cn(
        "border-0 hover:bg-transparent @max-[360px]:grid @max-[360px]:grid-cols-[auto_minmax(0,1fr)_auto] @max-[360px]:gap-x-3 @max-[360px]:gap-y-0.5 @max-[360px]:border-b @max-[360px]:border-(--ds-border) @max-[360px]:py-1.5",
        sum && "@max-[360px]:pt-0",
      )}
    >
      <TableHead
        scope="row"
        className={cn(
          cell,
          "font-normal whitespace-normal text-(--ds-muted) @max-[360px]:col-span-full",
          sum && "@max-[360px]:border-t-2 @max-[360px]:pt-1.5",
        )}
      >
        {row.label}
      </TableHead>
      <TableCell className={cn(cell, "text-right font-bold @max-[360px]:text-left @max-[360px]:whitespace-normal")}>
        {text}
      </TableCell>
      <TableCell
        className={cn(
          cell,
          "text-(--ds-muted) @max-[360px]:whitespace-normal @max-[360px]:before:content-['limit_'_/_'']",
        )}
      >
        {row.limit}
      </TableCell>
      <TableCell
        className={cn(
          cell,
          "text-right @max-[360px]:whitespace-normal",
          good ? "font-bold" : "font-semibold text-(--ds-muted)",
        )}
      >
        {good ? READOUT_CHECK.good : READOUT_CHECK.notYet}
      </TableCell>
    </TableRow>
  )
}
