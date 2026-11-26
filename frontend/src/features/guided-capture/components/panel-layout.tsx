import { cn } from "cn"
import type { ReactNode } from "react"
import { PanelDetails, type PanelDetailsLabel } from "@/features/guided-capture/components/panel-details"

const PANEL_HEAD = "flex min-w-0 flex-none flex-col gap-4 lg:px-5 lg:pt-5"
const COLUMN = "flex min-w-0 flex-col gap-4"

type PanelLayoutProps = {
  label: PanelDetailsLabel
  wide: boolean
  head?: ReactNode
  main?: ReactNode
  side?: ReactNode
  readout: ReactNode
}

export function PanelLayout({ label, wide, head, main, side, readout }: PanelLayoutProps) {
  if (wide) {
    return (
      <>
        {head === undefined ? null : <div className={PANEL_HEAD}>{head}</div>}
        <PanelDetails label={label}>
          {main}
          {side}
          {readout}
        </PanelDetails>
      </>
    )
  }
  const right = side ?? readout
  const twoUp = right !== null && right !== undefined
  return (
    <PanelDetails label={label}>
      <div className="@container min-w-0">
        <div className={cn("grid gap-4", twoUp && "@min-[560px]:grid-cols-2 @min-[560px]:items-start")}>
          <div className={COLUMN}>
            {head}
            {main}
          </div>
          {twoUp ? <div className={COLUMN}>{right}</div> : null}
        </div>
      </div>
      {side === undefined ? null : readout}
    </PanelDetails>
  )
}
