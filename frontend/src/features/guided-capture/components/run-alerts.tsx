import { ErrorAlert } from "@/features/guided-capture/components/error-alert"
import { plainError } from "@/features/guided-capture/lib/run-copy"
import type { AppError } from "@/lib/errors"

type RunAlertsProps = {
  errors: readonly (AppError | null)[]
}

export function RunAlerts({ errors }: RunAlertsProps) {
  return errors.map((error, slot) =>
    error === null ? null : <ErrorAlert key={`${slot}-${error.code}`} error={plainError(error)} />,
  )
}
