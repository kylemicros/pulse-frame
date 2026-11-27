import { LockSimpleIcon } from "@phosphor-icons/react"
import { useEffect, useRef, useState, type FocusEvent, type PointerEvent } from "react"
import { LOCK_WORDS } from "@/features/guided-capture/lib/run-copy"

type PrivacyLockProps = {
  shown: boolean
}

export function PrivacyLock({ shown: lockShown }: PrivacyLockProps) {
  const [hovered, setHovered] = useState(false)
  const [keyFocused, setKeyFocused] = useState(false)
  const [tapped, setTapped] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [wasShown, setWasShown] = useState(lockShown)
  const rootRef = useRef<HTMLSpanElement>(null)
  const touchedRef = useRef(false)
  if (wasShown !== lockShown) {
    setWasShown(lockShown)
    if (!lockShown) {
      setHovered(false)
      setKeyFocused(false)
      setTapped(false)
      setDismissed(false)
    }
  }
  const shown = lockShown && !dismissed && (hovered || keyFocused || tapped)

  useEffect(() => {
    if (!shown) {
      return undefined
    }
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDismissed(true)
      }
    }
    const untapOutside = (event: globalThis.PointerEvent) => {
      if (!(event.target instanceof Node && rootRef.current?.contains(event.target))) {
        setTapped(false)
      }
    }
    document.addEventListener("keydown", dismissOnEscape)
    document.addEventListener("pointerdown", untapOutside)
    return () => {
      document.removeEventListener("keydown", dismissOnEscape)
      document.removeEventListener("pointerdown", untapOutside)
    }
  }, [shown])

  const enter = (event: PointerEvent) => {
    if (event.pointerType === "mouse") {
      setHovered(true)
      setDismissed(false)
    }
  }
  const leave = (event: PointerEvent) => {
    if (event.pointerType === "mouse") {
      setHovered(false)
    }
  }
  const focus = (event: FocusEvent<HTMLButtonElement>) => {
    if (event.currentTarget.matches(":focus-visible")) {
      setKeyFocused(true)
      setDismissed(false)
    }
  }
  const tap = () => {
    if (touchedRef.current) {
      touchedRef.current = false
      setTapped((on) => !on)
      setDismissed(false)
    }
  }

  return (
    <span
      ref={rootRef}
      onPointerEnter={enter}
      onPointerLeave={leave}
      className="absolute top-3 left-3 z-10 flex items-center"
    >
      <button
        type="button"
        aria-label={LOCK_WORDS}
        onFocus={focus}
        onBlur={() => setKeyFocused(false)}
        onPointerDown={(event) => {
          touchedRef.current = event.pointerType !== "mouse"
        }}
        onClick={tap}
        className="inline-grid size-11 flex-none cursor-pointer place-items-center rounded-full border border-(--ds-edge) bg-[color-mix(in_srgb,var(--ds-surface)_92%,transparent)] p-0 text-(--ds-muted) hover:text-(--ds-text) focus-visible:text-(--ds-text) focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count)"
      >
        <LockSimpleIcon aria-hidden="true" size={20} />
      </button>
      <span
        aria-hidden="true"
        className={
          shown
            ? "ml-1.5 animate-quick-in rounded-md bg-(--ds-text) px-2.5 py-1 font-sans text-sm/snug font-semibold whitespace-nowrap text-(--ds-bg) shadow-[0_4px_12px_rgba(0,0,0,0.2)] motion-reduce:animate-none"
            : "hidden"
        }
      >
        {LOCK_WORDS}
      </span>
    </span>
  )
}
