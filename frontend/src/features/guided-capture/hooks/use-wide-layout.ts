import { useSyncExternalStore } from "react"

const WIDE_QUERY = "(min-width: 64rem)"

let wideList: MediaQueryList | null = null

function wideQuery(): MediaQueryList {
  wideList ??= globalThis.matchMedia(WIDE_QUERY)
  return wideList
}

function subscribe(onChange: () => void): () => void {
  const list = wideQuery()
  list.addEventListener("change", onChange)
  return () => list.removeEventListener("change", onChange)
}

function isWide(): boolean {
  return wideQuery().matches
}

export function useWideLayout(): boolean {
  return useSyncExternalStore(subscribe, isWide, () => false)
}
