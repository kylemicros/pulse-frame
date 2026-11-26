import { MonitorIcon, MoonIcon, SunIcon, type Icon } from "@phosphor-icons/react"
import { Radio } from "@base-ui/react/radio"
import { RadioGroup } from "@base-ui/react/radio-group"
import { useId } from "react"
import { isThemeChoice } from "@/features/settings/lib/theme"
import type { ThemeChoice as Choice } from "@/features/settings/types"

const CHOICES: readonly { value: Choice; label: string; icon: Icon }[] = [
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
  { value: "system", label: "System", icon: MonitorIcon },
]

type ThemeChoiceProps = {
  choice: Choice
  onChoose: (choice: Choice) => void
}

export function ThemeChoice({ choice, onChoose }: ThemeChoiceProps) {
  const labelId = useId()
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-(--ds-border) px-3 py-2">
      <span id={labelId} className="font-bold">
        Theme
      </span>
      <RadioGroup
        aria-labelledby={labelId}
        value={choice}
        onValueChange={(value) => {
          if (isThemeChoice(value)) {
            onChoose(value)
          }
        }}
        className="grid grid-cols-3 overflow-hidden rounded-md border border-(--ds-edge)"
      >
        {CHOICES.map(({ value, label, icon: ChoiceIcon }) => (
          <Radio.Root
            key={value}
            value={value}
            className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-1.5 border-l border-(--ds-edge) bg-(--ds-surface) text-[0.9375rem] font-semibold text-(--ds-text) first:border-l-0 focus-visible:outline-3 focus-visible:-outline-offset-3 focus-visible:outline-(--ds-count) data-checked:bg-(--ds-primary-bg) data-checked:font-bold data-checked:text-(--ds-primary-text)"
          >
            <ChoiceIcon aria-hidden="true" size={18} />
            {label}
          </Radio.Root>
        ))}
      </RadioGroup>
    </div>
  )
}
