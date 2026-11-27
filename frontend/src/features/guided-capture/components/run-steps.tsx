import { cn } from "cn"
import type { ReactNode } from "react"
import type { Stage } from "@/features/guided-capture/types"

const STEPS: readonly { stage: Stage; name: string; plan: string }[] = [
  { stage: "get-comfy", name: "Get comfy", plan: "" },
  { stage: "warm-up", name: "Warm-up", plan: "60 s" },
  { stage: "counted", name: "Counted", plan: "90 s" },
  { stage: "result", name: "Result", plan: "" },
]

const PHONE_HIDDEN = "max-md:sr-only"
const TAG = "font-mono text-xs font-bold tracking-wide text-(--ds-text) uppercase"

type RunStepsProps = {
  stage: Stage
  stopped: Stage | null
  className?: string
}

function stepMark(position: number, done: boolean, halted: boolean): ReactNode {
  if (done) {
    return (
      <svg viewBox="0 0 12 12" className="size-3" focusable="false">
        <polyline points="2,6.5 5,9 10,3" className="fill-none stroke-(--ds-text) stroke-2" />
      </svg>
    )
  }
  if (halted) {
    return (
      <svg viewBox="0 0 12 12" className="size-2.5" focusable="false">
        <rect x="2" y="2" width="8" height="8" rx="1" className="fill-(--ds-text)" />
      </svg>
    )
  }
  return position + 1
}

export function RunSteps({ stage, stopped, className }: RunStepsProps) {
  const halt = stopped === null ? -1 : STEPS.findIndex((step) => step.stage === stopped)
  const current = stopped === null ? STEPS.findIndex((step) => step.stage === stage) : -1
  const reached = stopped === null ? current : halt
  return (
    <ol aria-label="Capture steps" className={cn("flex min-w-0 items-center gap-1.5", className)}>
      {STEPS.map((step, position) => {
        const now = position === current
        const halted = position === halt
        const done = position < reached
        const named = now || halted
        return (
          <li
            key={step.stage}
            aria-current={now ? "step" : undefined}
            className={cn(
              "flex items-center gap-1.5 rounded-full border py-1 pr-3 pl-1.25 text-sm whitespace-nowrap text-(--ds-muted)",
              now && "border-2 border-(--ds-text) py-0.75 pr-2.75 pl-1",
              halted && "border-2 border-dashed border-(--ds-edge) py-0.75 pr-2.75 pl-1",
              !now && !halted && "border-(--ds-border)",
              !named && "max-md:p-1",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "inline-grid size-6 flex-none place-items-center rounded-full border-2 font-mono text-xs font-bold",
                now ? "border-(--ds-text) bg-(--ds-text) text-(--ds-surface)" : "border-(--ds-edge) text-(--ds-text)",
                halted && "border-dashed",
              )}
            >
              {stepMark(position, done, halted)}
            </span>
            <span className={cn("font-semibold text-(--ds-text)", !named && PHONE_HIDDEN)}>{step.name}</span>
            {now ? <span className={TAG}>Now</span> : null}
            {halted ? <span className={TAG}>Stopped</span> : null}
            {done ? <span className="sr-only">, done</span> : null}
            {!named && !done && step.plan !== "" ? (
              <span className={cn("font-mono", PHONE_HIDDEN)}>{step.plan}</span>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
