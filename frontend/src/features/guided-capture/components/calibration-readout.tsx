import { useId } from "react"
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { CalibrationReadoutRow } from "@/features/guided-capture/components/calibration-readout-row"
import {
  checkEndLine,
  clearShareRow,
  measureRows,
  READOUT_COLUMNS,
  READOUT_FOOT,
  READOUT_HEADING,
  READOUT_NOTE,
  READOUT_PHASE,
} from "@/features/guided-capture/lib/calibration-readout"
import { setupFps, type SetupCheck } from "@/features/guided-capture/lib/setup-check"
import type { CheckEnd, RunResult } from "@/features/guided-capture/types"

const COLUMN = "h-auto px-1.5 py-1 align-bottom font-semibold whitespace-nowrap text-(--ds-muted) border-b border-(--ds-border)"

type CalibrationReadoutProps = {
  check: SetupCheck | null
  now: number
  checkEnd: CheckEnd | null
  result: RunResult | null
}

export function CalibrationReadout({ check, now, checkEnd, result }: CalibrationReadoutProps) {
  const headingId = useId()
  const live = check !== null
  const frozen = check === null && checkEnd !== null ? measureRows(checkEnd.sample, checkEnd.fps, true) : null
  const rows = check === null ? frozen : measureRows(check.sample, setupFps(check, now), false)
  if (rows === null) {
    return null
  }
  const noReading = result?.kind === "none" ? result : null
  return (
    <section
      aria-labelledby={headingId}
      className="@container min-w-0 rounded-lg border border-dashed border-(--ds-edge) bg-(--ds-surface-2) p-3 font-mono text-sm text-(--ds-text) tabular-nums wrap-anywhere"
    >
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
        <h3 id={headingId} className="text-xs font-bold tracking-[0.06em] uppercase">
          {READOUT_HEADING}
        </h3>
        <span className="text-(--ds-muted)">{live ? READOUT_PHASE.live : READOUT_PHASE.frozen}</span>
      </div>
      <p className="mb-2 text-(--ds-muted)">{READOUT_NOTE}</p>
      {result === null || checkEnd === null ? null : <p className="mb-2 font-bold">{checkEndLine(checkEnd)}</p>}
      <Table className="text-sm @max-[312px]:block">
        <TableHeader className="@max-[312px]:sr-only">
          <TableRow className="border-0 hover:bg-transparent">
            <TableHead scope="col" className={COLUMN}>
              {READOUT_COLUMNS.measure}
            </TableHead>
            <TableHead scope="col" className={`${COLUMN} text-right`}>
              {live ? READOUT_COLUMNS.live : READOUT_COLUMNS.frozen}
            </TableHead>
            <TableHead scope="col" className={COLUMN}>
              {READOUT_COLUMNS.limit}
            </TableHead>
            <TableHead scope="col" className={`${COLUMN} text-right`}>
              {READOUT_COLUMNS.check}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody className="@max-[312px]:block @max-[312px]:w-full">
          {rows.map((row) => (
            <CalibrationReadoutRow key={row.label} row={row} live={live} />
          ))}
          {noReading === null ? null : (
            <CalibrationReadoutRow row={clearShareRow(noReading.clearPercent)} live={false} sum />
          )}
        </TableBody>
      </Table>
      {noReading === null ? null : <p className="mt-2 font-sans text-(--ds-muted)">{READOUT_FOOT}</p>}
    </section>
  )
}
