import { cn } from "cn"
import { StartAnyway } from "@/features/guided-capture/components/start-anyway"
import { SETUP_START_ANYWAY_MS, setupRows, type SetupCheck } from "@/features/guided-capture/lib/setup-check"
import {
  ALL_GOOD_SAID,
  SETUP_ROWS,
  setupPromptText,
  START_ANYWAY_SAID,
} from "@/features/guided-capture/lib/setup-copy"

type SetupCheckStatusProps = {
  check: SetupCheck
  now: number
  onStartAnyway: () => void
  onFocusLeave: () => void
}

export function SetupCheckStatus({ check, now, onStartAnyway, onFocusLeave }: SetupCheckStatusProps) {
  const rows = setupRows(check, now)
  const allGood = check.shown === "allGood"
  const elapsed = now - check.startedAt
  const prompt = setupPromptText(check)
  return (
    <>
      <div className="@container">
        <ul
          aria-label="Setup check"
          className="grid grid-cols-1 gap-1.5 @min-[424px]:grid-cols-2 @min-[880px]:grid-cols-4"
        >
          {SETUP_ROWS.map(({ row, name }) => {
            const good = rows[row]
            return (
              <li
                key={row}
                className="flex min-w-0 items-center gap-2 rounded-lg border border-(--ds-border) px-2.5 py-2 text-sm"
              >
                <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false" className="size-5 flex-none">
                  {good ? (
                    <>
                      <circle cx="10" cy="10" r="9" className="fill-(--ds-text)" />
                      <polyline
                        points="6,10.5 9,13 14,7"
                        className="fill-none stroke-(--ds-surface) stroke-2 [stroke-linecap:round] [stroke-linejoin:round]"
                      />
                    </>
                  ) : (
                    <circle cx="10" cy="10" r="8" className="fill-none stroke-(--ds-edge) stroke-2 [stroke-dasharray:3_3]" />
                  )}
                </svg>
                <span className="font-semibold whitespace-nowrap">{name}</span>
                <span
                  className={cn("ml-auto whitespace-nowrap", good ? "font-bold" : "font-semibold text-(--ds-muted)")}
                >
                  {good ? "Good" : "Not yet"}
                </span>
              </li>
            )
          })}
        </ul>
      </div>
      {allGood ? null : (
        <StartAnyway elapsed={elapsed} onStartAnyway={onStartAnyway} onFocusLeave={onFocusLeave} />
      )}
      <output className="sr-only">{allGood ? ALL_GOOD_SAID : (prompt ?? "")}</output>
      <output className="sr-only">{elapsed >= SETUP_START_ANYWAY_MS ? START_ANYWAY_SAID : ""}</output>
    </>
  )
}
