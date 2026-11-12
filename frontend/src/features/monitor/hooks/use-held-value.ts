import { useEffect, useRef, useState } from "react"

export const HOLD_MS = 400

export function useHeldValue<T extends string>(value: T, holdMs: number = HOLD_MS): T {
  const [shown, setShown] = useState(value)
  const shownAt = useRef(0)

  useEffect(() => {
    if (value === shown) {
      return undefined
    }
    const wait = Math.max(0, shownAt.current + holdMs - performance.now())
    const timer = window.setTimeout(() => {
      shownAt.current = performance.now()
      setShown(value)
    }, wait)
    return () => window.clearTimeout(timer)
  }, [value, shown, holdMs])

  return shown
}
