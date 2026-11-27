import { useCallback, useLayoutEffect, useState } from "react"
import { keepTheme, readTheme, showTheme } from "@/features/settings/lib/theme"
import type { ThemeChoice } from "@/features/settings/types"

export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(readTheme)

  useLayoutEffect(() => {
    showTheme(choice)
  }, [choice])

  const choose = useCallback((next: ThemeChoice) => {
    setChoice(next)
    keepTheme(next)
  }, [])

  return { choice, choose }
}
