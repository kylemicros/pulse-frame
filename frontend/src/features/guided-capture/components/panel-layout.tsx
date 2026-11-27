import { cn } from "cn"
import type { ReactNode } from "react"
import { PanelDetails, type PanelDetailsLabel } from "@/features/guided-capture/components/panel-details"

const STACK = "flex min-w-0 flex-col gap-4"
const FADE = "animate-phase-in motion-reduce:animate-none"
const WIDE_EDGE = "flex-none lg:px-5"

type PanelLayoutProps = {
  label: PanelDetailsLabel
  wide: boolean
  head?: ReactNode
  alerts?: ReactNode
  main?: ReactNode
  side?: ReactNode
  readout: ReactNode
}

export function PanelLayout({ label, wide, head, alerts, main, side, readout }: PanelLayoutProps) {
  const headPart =
    head === undefined ? null : (
      <div key={`head-${label}`} className={cn(STACK, FADE, wide && cn(WIDE_EDGE, "lg:pt-5"))}>
        {head}
      </div>
    )
  const alertsPart = <div className={cn(STACK, "empty:hidden", wide && cn(WIDE_EDGE, "lg:pt-4"))}>{alerts}</div>
  const mainPart =
    main === undefined ? null : (
      <div key={`main-${label}`} className={cn(STACK, FADE)}>
        {main}
      </div>
    )
  if (wide) {
    return (
      <>
        {headPart}
        {alertsPart}
        <PanelDetails label={label}>
          {mainPart}
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
          <div className={STACK}>
            {headPart}
            {alertsPart}
            {mainPart}
          </div>
          {twoUp ? <div className={STACK}>{right}</div> : null}
        </div>
      </div>
      {side === undefined ? null : readout}
    </PanelDetails>
  )
}
