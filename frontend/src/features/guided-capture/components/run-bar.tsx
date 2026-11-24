import { Progress } from "@base-ui/react/progress"
import { cn } from "cn"

type RunBarProps = {
  label: string
  percent: number
  valueText: string
  fillClassName: string
  thin?: boolean
  labelShown?: boolean
}

export function RunBar({ label, percent, valueText, fillClassName, thin = false, labelShown = false }: RunBarProps) {
  return (
    <Progress.Root
      value={percent}
      min={0}
      max={100}
      aria-label={labelShown ? undefined : label}
      getAriaValueText={() => valueText}
    >
      {labelShown ? (
        <div className="mb-1 flex flex-wrap justify-between gap-x-2 text-sm">
          <Progress.Label>{label}</Progress.Label>
          <Progress.Value className="font-mono font-bold tabular-nums">
            {(_formatted, value) => `${value ?? 0}%`}
          </Progress.Value>
        </div>
      ) : null}
      <Progress.Track
        className={cn(
          "block overflow-hidden rounded-full border border-(--ds-edge) bg-(--ds-track)",
          thin ? "h-2" : "h-3",
        )}
      >
        <Progress.Indicator
          className={cn("block h-full rounded-full transition-[width] duration-200 ease-linear motion-reduce:transition-none", fillClassName)}
        />
      </Progress.Track>
    </Progress.Root>
  )
}
