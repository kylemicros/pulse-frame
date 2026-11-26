import { useLayoutEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { RunBar } from "@/features/guided-capture/components/run-bar"
import { countdownSeconds, percentDone } from "@/features/guided-capture/lib/run-plan"
import { SETUP_START_ANYWAY_MS } from "@/features/guided-capture/lib/setup-check"
import { secondsToGo, START_ANYWAY_READY, startAnywayIn } from "@/features/guided-capture/lib/setup-copy"

type StartAnywayProps = {
  elapsed: number
  onStartAnyway: () => void
  onFocusLeave: () => void
}

export function StartAnyway({ elapsed, onStartAnyway, onFocusLeave }: StartAnywayProps) {
  const boxRef = useRef<HTMLDivElement>(null)
  const ready = elapsed >= SETUP_START_ANYWAY_MS
  const left = countdownSeconds(SETUP_START_ANYWAY_MS, elapsed)

  useLayoutEffect(() => {
    const box = boxRef.current
    return () => {
      if (box !== null && box.contains(document.activeElement)) {
        onFocusLeave()
      }
    }
  }, [onFocusLeave])

  return (
    <div ref={boxRef} className="flex flex-col gap-2 rounded-lg border border-(--ds-border) p-3">
      <p className="text-sm">{ready ? START_ANYWAY_READY : startAnywayIn(left)}</p>
      {ready ? (
        <Button
          variant="outline"
          onClick={onStartAnyway}
          className="h-auto min-h-11 self-start rounded-md border-(--ds-edge) bg-(--ds-surface) px-3.5 text-base font-semibold text-(--ds-text) focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count) dark:border-(--ds-edge) dark:bg-(--ds-surface)"
        >
          Start anyway
        </Button>
      ) : (
        <RunBar
          label="Until start anyway shows up"
          thin
          percent={percentDone(elapsed, 0, SETUP_START_ANYWAY_MS)}
          valueText={secondsToGo(left)}
          fillClassName="bg-(--ds-muted)"
        />
      )}
    </div>
  )
}
