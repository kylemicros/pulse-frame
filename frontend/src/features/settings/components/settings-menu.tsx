import { Dialog } from "@base-ui/react/dialog"
import { GearSixIcon, LockSimpleIcon, XIcon } from "@phosphor-icons/react"
import { cn } from "cn"
import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react"
import { SettingSwitch } from "@/features/settings/components/setting-switch"
import { ThemeChoice } from "@/features/settings/components/theme-choice"
import { useTheme } from "@/features/settings/hooks/use-theme"
import { wrappedTabStop } from "@/features/settings/lib/tab-wrap"
import type { SettingSwitchItem } from "@/features/settings/types"

const PRIVACY_SENTENCE = "Your video stays on this computer. No frame is ever saved."

const QUIET_ICON_BUTTON =
  "inline-grid size-11 flex-none cursor-pointer place-items-center rounded-lg border-0 bg-transparent p-0 text-(--ds-muted) hover:text-(--ds-text) focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count)"

function keepTabInside(event: KeyboardEvent<HTMLDivElement>): void {
  if (event.key !== "Tab") {
    return
  }
  const next = wrappedTabStop(event.currentTarget, document.activeElement, event.shiftKey)
  if (next !== null) {
    event.preventDefault()
    next.focus()
  }
}

type SettingsMenuProps = {
  switches: readonly SettingSwitchItem[]
  trailingSwitches: readonly SettingSwitchItem[]
  sheet: boolean
  container: RefObject<HTMLElement | null>
}

export function SettingsMenu({ switches, trailingSwitches, sheet, container }: SettingsMenuProps) {
  const { choice, choose } = useTheme()
  const gearRef = useRef<HTMLButtonElement>(null)
  const firstRef = useRef<HTMLElement>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open || !sheet) {
      return undefined
    }
    const { style } = document.documentElement
    const before = style.overflow
    style.overflow = "hidden"
    return () => {
      style.overflow = before
    }
  }, [open, sheet])

  return (
    <Dialog.Root modal={false} open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        ref={gearRef}
        aria-label="Settings"
        className={cn(QUIET_ICON_BUTTON, "data-popup-open:text-(--ds-text)")}
      >
        <GearSixIcon aria-hidden="true" size={22} />
      </Dialog.Trigger>
      <Dialog.Portal container={sheet ? undefined : container}>
        {sheet ? <Dialog.Backdrop className="fixed inset-0 z-40 bg-black/50" /> : null}
        <Dialog.Popup
          initialFocus={firstRef}
          finalFocus={gearRef}
          aria-modal={sheet ? true : undefined}
          onKeyDown={sheet ? keepTabInside : undefined}
          className={cn(
            "z-50 flex flex-col gap-3 overflow-y-auto overscroll-contain border-(--ds-edge) bg-(--ds-surface) font-sans text-base/normal text-(--ds-text) outline-none",
            sheet
              ? "fixed inset-x-0 bottom-0 max-h-[85dvh] rounded-t-2xl border-t px-safe-4 pt-2 pb-[max(--spacing(4),env(safe-area-inset-bottom))]"
              : "absolute top-2 right-0 max-h-[calc(100dvh-6rem)] w-90 rounded-[10px] border p-4 shadow-[0_12px_32px_rgba(0,0,0,0.22)]",
          )}
        >
          {sheet ? <div aria-hidden="true" className="mx-auto mb-1 h-1.25 w-10 flex-none rounded-full bg-(--ds-edge)" /> : null}
          <div className="flex items-center justify-between gap-3">
            <Dialog.Title className="text-xl/tight font-bold">Settings</Dialog.Title>
            <Dialog.Close aria-label="Close settings" className={QUIET_ICON_BUTTON}>
              <XIcon aria-hidden="true" size={22} />
            </Dialog.Close>
          </div>
          <ul className="grid gap-2">
            {switches.map((item, index) => (
              <li key={item.name}>
                <SettingSwitch {...item} ref={index === 0 ? firstRef : undefined} />
              </li>
            ))}
            <li>
              <ThemeChoice choice={choice} onChoose={choose} />
            </li>
            {trailingSwitches.map((item) => (
              <li key={item.name}>
                <SettingSwitch {...item} />
              </li>
            ))}
          </ul>
          <p className="flex items-center gap-1.5 text-sm text-(--ds-muted)">
            <LockSimpleIcon aria-hidden="true" size={16} className="flex-none" />
            <span>{PRIVACY_SENTENCE}</span>
          </p>
          {sheet ? (
            <Dialog.Close className="min-h-11 w-full flex-none cursor-pointer rounded-md border-2 border-(--ds-primary-bg) bg-(--ds-primary-bg) px-5 py-2.5 font-bold text-(--ds-primary-text) focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count)">
              Done
            </Dialog.Close>
          ) : null}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
