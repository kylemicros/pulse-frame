import type { AppError } from "@/lib/errors"

type ErrorAlertProps = {
  error: AppError
}

export function ErrorAlert({ error }: ErrorAlertProps) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-1 rounded-md border border-l-4 border-(--ds-edge) border-l-(--ds-alert-edge) bg-(--ds-alert-bg) px-4 py-3 text-(--ds-text)"
    >
      <p>{error.message}</p>
      <p>{error.action}</p>
      <p className="font-mono text-sm text-(--ds-muted)">{`Ref: ${error.code}`}</p>
    </div>
  )
}
