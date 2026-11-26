import { useMemo, useState, useSyncExternalStore } from "react"

type ScrollState = "fits" | "overflows" | "fits-focused" | "overflows-focused"

type ScrollStore = {
  subscribe: (onChange: () => void) => () => void
  getSnapshot: () => ScrollState
}

function scrollStore(element: HTMLElement | null): ScrollStore {
  let overflowing = false
  let focused = false
  return {
    subscribe(onChange) {
      if (element === null) {
        return () => undefined
      }
      const observer = new ResizeObserver(() => {
        overflowing = element.scrollHeight > element.clientHeight + 1
        onChange()
      })
      const onFocus = () => {
        focused = true
        onChange()
      }
      const onBlur = () => {
        focused = false
        onChange()
      }
      observer.observe(element)
      for (const child of element.children) {
        observer.observe(child)
      }
      element.addEventListener("focus", onFocus)
      element.addEventListener("blur", onBlur)
      return () => {
        observer.disconnect()
        element.removeEventListener("focus", onFocus)
        element.removeEventListener("blur", onBlur)
      }
    },
    getSnapshot(): ScrollState {
      if (overflowing) {
        return focused ? "overflows-focused" : "overflows"
      }
      return focused ? "fits-focused" : "fits"
    },
  }
}

export type ScrollArea = { ref: (element: HTMLElement | null) => void; overflowing: boolean; focused: boolean }

export function useOverflowing(): ScrollArea {
  const [element, setElement] = useState<HTMLElement | null>(null)
  const store = useMemo(() => scrollStore(element), [element])
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, () => "fits" as const)
  return { ref: setElement, overflowing: state.startsWith("overflows"), focused: state.endsWith("-focused") }
}
