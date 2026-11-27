import { useMediaMatch } from "@/features/guided-capture/hooks/use-media-match"

const WIDE_QUERY = "(min-width: 64rem)"
const TABLET_UP_QUERY = "(min-width: 48rem)"

export function useWideLayout(): boolean {
  return useMediaMatch(WIDE_QUERY)
}

export function useTabletUp(): boolean {
  return useMediaMatch(TABLET_UP_QUERY)
}
