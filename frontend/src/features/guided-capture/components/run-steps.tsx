import { cn } from "cn"
import type { Stage } from "@/features/guided-capture/types"

const STEPS: readonly { stage: Stage; name: string; plan: string }[] = [
  { stage: "get-comfy", name: "Get comfy", plan: "" },
  { stage: "warm-up", name: "Warm-up", plan: "60 s" },
  { stage: "counted", name: "Counted", plan: "90 s" },
  { stage: "result", name: "Result", plan: "At the end" },
]

type RunStepsProps = {
  stage: Stage
}

export function RunSteps({ stage }: RunStepsProps) {
  const current = STEPS.findIndex((step) => step.stage === stage)
  return (
    <ol aria-label="Capture steps" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {STEPS.map((step, position) => {
        const now = position === current
        const done = position < current
        return (
          <li
            key={step.stage}
            aria-current={now ? "step" : undefined}
            className={cn(
              "flex flex-col gap-1 rounded-lg border px-2.5 py-2 text-sm",
              now ? "border-2 border-(--ds-text) text-(--ds-text)" : "border-(--ds-border) text-(--ds-muted)",
            )}
          >
            <span className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={cn(
                  "inline-grid size-5.5 flex-none place-items-center rounded-full border-2 font-mono text-xs font-bold",
                  now
                    ? "border-(--ds-text) bg-(--ds-text) text-(--ds-surface)"
                    : "border-(--ds-edge) text-(--ds-text)",
                )}
              >
                {done ? (
                  <svg viewBox="0 0 12 12" className="size-3" focusable="false">
                    <polyline points="2,6.5 5,9 10,3" className="fill-none stroke-(--ds-text) stroke-2" />
                  </svg>
                ) : (
                  position + 1
                )}
              </span>
              <span className="font-semibold text-(--ds-text)">{step.name}</span>
            </span>
            {now ? (
              <span className="font-mono text-xs font-bold tracking-wide uppercase">Now</span>
            ) : (
              <span>{done ? "Done" : step.plan}</span>
            )}
          </li>
        )
      })}
    </ol>
  )
}
