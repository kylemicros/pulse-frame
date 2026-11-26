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

const CELL = "h-auto px-1.5 py-1 align-top border-b border-(--ds-border) @max-[312px]:border-0 @max-[312px]:p-0"
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
        "border-0 hover:bg-transparent @max-[312px]:grid @max-[312px]:grid-cols-[auto_minmax(0,1fr)_auto] @max-[312px]:gap-x-3 @max-[312px]:gap-y-0.5 @max-[312px]:border-b @max-[312px]:border-(--ds-border) @max-[312px]:py-1.5",
        sum && "@max-[312px]:pt-0",
      )}
    >
      <TableHead
        scope="row"
        className={cn(
          cell,
          "font-normal whitespace-normal text-(--ds-muted) @max-[312px]:col-span-full",
          sum && "@max-[312px]:border-t-2 @max-[312px]:pt-1.5",
        )}
      >
        {row.label}
      </TableHead>
      <TableCell className={cn(cell, "text-right font-bold @max-[312px]:text-left @max-[312px]:whitespace-normal")}>
        {text}
      </TableCell>
      <TableCell
        className={cn(
          cell,
          "text-(--ds-muted) @max-[312px]:whitespace-normal @max-[312px]:before:content-['limit_'_/_'']",
        )}
      >
        {row.limit}
      </TableCell>
      <TableCell
        className={cn(
          cell,
          "text-right @max-[312px]:whitespace-normal",
          good ? "font-bold" : "font-semibold text-(--ds-muted)",
        )}
      >
        {good ? READOUT_CHECK.good : READOUT_CHECK.notYet}
      </TableCell>
    </TableRow>
  )
}
