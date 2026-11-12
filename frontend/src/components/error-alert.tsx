import type { AppError } from "@/lib/errors"

type ErrorAlertProps = {
  error: AppError
}

export function ErrorAlert({ error }: ErrorAlertProps) {
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
