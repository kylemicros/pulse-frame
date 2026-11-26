import type { ReactNode } from "react"
import { useOverflowing } from "@/features/guided-capture/hooks/use-overflowing"

export type PanelDetailsLabel =
  | "Setup check details"
  | "Warm-up details"
  | "Counting details"
  | "Run details"
  | "Run plan"

const FRAME = [
  "relative flex min-w-0 flex-col lg:min-h-0 lg:flex-1",
  "after:pointer-events-none after:absolute after:inset-0 after:z-2",
  "has-[>section:focus-visible]:after:outline-3 has-[>section:focus-visible]:after:-outline-offset-3",
  "has-[>section:focus-visible]:after:outline-(--ds-count)",
].join(" ")

const SCROLL_AREA = [
  "flex flex-col outline-none",
  "lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:overscroll-contain lg:pr-3 lg:pl-5 lg:panel-scrollbar",
  "lg:before:pointer-events-none lg:before:sticky lg:before:top-0 lg:before:z-1 lg:before:h-6 lg:before:flex-none",
  "lg:before:bg-linear-to-b lg:before:from-(--ds-surface) lg:before:to-transparent",
  "lg:after:pointer-events-none lg:after:sticky lg:after:bottom-0 lg:after:z-1 lg:after:h-12 lg:after:flex-none",
  "lg:after:bg-linear-to-b lg:after:from-transparent lg:after:to-(--ds-surface) lg:after:to-85%",
].join(" ")

type PanelDetailsProps = {
  label: PanelDetailsLabel
  children: ReactNode
}

export function PanelDetails({ label, children }: PanelDetailsProps) {
  const { ref, overflowing, focused } = useOverflowing()
  return (
    <div className={FRAME}>
      <section
        ref={ref}
        aria-label={label}
        // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={overflowing || focused ? 0 : undefined}
        className={SCROLL_AREA}
      >
        <div className="flex min-w-0 flex-none flex-col gap-4">{children}</div>
      </section>
    </div>
  )
}
