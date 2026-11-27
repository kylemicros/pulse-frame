import type { ReactNode } from "react"

export type ThemeChoice = "light" | "dark" | "system"

export type SettingSwitchItem = {
  name: string
  line: ReactNode
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}
