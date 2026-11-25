import { Button } from "@/components/ui/button"

type ToggleButtonProps = {
  label: string
  pressed: boolean
  onToggle: () => void
}

export function ToggleButton({ label, pressed, onToggle }: ToggleButtonProps) {
  return (
    <Button
      variant="outline"
      aria-pressed={pressed}
      onClick={onToggle}
      className="h-auto min-h-11 self-start rounded-md border-(--ds-edge) bg-(--ds-surface) px-3.5 text-base font-semibold text-(--ds-text) focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count) dark:border-(--ds-edge) dark:bg-(--ds-surface)"
    >
      {`${label}: ${pressed ? "on" : "off"}`}
    </Button>
  )
}
