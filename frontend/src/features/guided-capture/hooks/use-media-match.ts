import { useCallback, useSyncExternalStore } from "react"

const lists = new Map<string, MediaQueryList>()

function listFor(query: string): MediaQueryList {
  let list = lists.get(query)
  if (list === undefined) {
    list = globalThis.matchMedia(query)
    lists.set(query, list)
  }
  return list
}

export function useMediaMatch(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = listFor(query)
      list.addEventListener("change", onChange)
      return () => list.removeEventListener("change", onChange)
    },
    [query],
  )
  const matches = useCallback(() => listFor(query).matches, [query])
  return useSyncExternalStore(subscribe, matches, () => false)
}
