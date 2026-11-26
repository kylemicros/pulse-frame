import { Switch } from "@base-ui/react/switch"
import type { Ref } from "react"
import type { SettingSwitchItem } from "@/features/settings/types"

type SettingSwitchProps = SettingSwitchItem & {
  ref?: Ref<HTMLElement>
}

export function SettingSwitch({ name, line, checked, onCheckedChange, ref }: SettingSwitchProps) {
  return (
    <Switch.Root
      ref={ref}
      checked={checked}
      onCheckedChange={(next) => onCheckedChange(next)}
      className="group flex min-h-14 w-full cursor-pointer items-center gap-3 rounded-lg border border-(--ds-border) bg-(--ds-surface) px-3 py-2 text-left text-(--ds-text) focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count)"
    >
      <span className="flex min-w-0 flex-1 flex-col leading-snug">
        <span className="font-bold">{name}</span>
        <span className="text-sm text-(--ds-muted)">{line}</span>
      </span>
      <span
        aria-hidden="true"
        className="relative h-4.5 w-7.5 flex-none rounded-full border-2 border-(--ds-edge) bg-(--ds-track) group-data-checked:border-(--ds-count) group-data-checked:bg-(--ds-count)"
      >
        <Switch.Thumb className="absolute top-0.5 left-0.5 size-2.5 rounded-full bg-(--ds-edge) data-checked:left-3.5 data-checked:bg-(--ds-surface)" />
      </span>
      <span aria-hidden="true" className="min-w-7 font-mono text-sm font-bold">
        {checked ? "On" : "Off"}
      </span>
    </Switch.Root>
  )
}
