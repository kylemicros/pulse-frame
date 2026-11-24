import type { AppError } from "@/lib/errors"

type ErrorAlertProps = {
  error: AppError
  form?: "code-first" | "quiet-ref"
}

export function ErrorAlert({ error, form = "code-first" }: ErrorAlertProps) {
  if (form === "quiet-ref") {
    return (
      <div
        role="alert"
        className="flex flex-col gap-1 rounded-md border border-l-4 border-(--ds-edge) border-l-(--ds-warm) bg-(--ds-alert-bg) px-4 py-3 text-(--ds-text)"
      >
        <p>{error.message}</p>
        <p>{error.action}</p>
        <p className="font-mono text-sm text-(--ds-muted)">{`Ref: ${error.code}`}</p>
      </div>
    )
  }
  return (
    <div role="alert" className="flex flex-col gap-1 border border-destructive/40 bg-destructive/10 p-3 text-sm text-foreground">
      <p>
        <span className="font-semibold text-destructive">{error.code}</span>{" "}
        {error.message}
      </p>
      <p className="text-muted-foreground">{error.action}</p>
    </div>
  )
}
