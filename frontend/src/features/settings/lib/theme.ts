import type { ThemeChoice } from "@/features/settings/types"

const THEME_KEY = "theme"

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === "light" || value === "dark" || value === "system"
}

export function readTheme(): ThemeChoice {
  try {
    const saved = globalThis.localStorage.getItem(THEME_KEY)
    return isThemeChoice(saved) ? saved : "system"
  } catch (error) {
    if (error instanceof DOMException) {
      return "system"
    }
    throw error
  }
}

export function keepTheme(choice: ThemeChoice): void {
  try {
    if (choice === "system") {
      globalThis.localStorage.removeItem(THEME_KEY)
    } else {
      globalThis.localStorage.setItem(THEME_KEY, choice)
    }
  } catch (error) {
    if (!(error instanceof DOMException)) {
      throw error
    }
  }
}

type Scheme = Exclude<ThemeChoice, "system">

const SCHEME_MEDIA: Record<Scheme, string> = {
  light: "(prefers-color-scheme: light)",
  dark: "(prefers-color-scheme: dark)",
}

let schemeMetas: readonly { scheme: Scheme; meta: HTMLMetaElement }[] | null = null

function themeColorMetas(): readonly { scheme: Scheme; meta: HTMLMetaElement }[] {
  schemeMetas ??= Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')).flatMap(
    (meta): { scheme: Scheme; meta: HTMLMetaElement }[] => {
      if (meta.media === SCHEME_MEDIA.light) {
        return [{ scheme: "light", meta }]
      }
      return meta.media === SCHEME_MEDIA.dark ? [{ scheme: "dark", meta }] : []
    },
  )
  return schemeMetas
}

export function showTheme(choice: ThemeChoice): void {
  const { classList } = document.documentElement
  classList.toggle("light", choice === "light")
  classList.toggle("dark", choice === "dark")
  for (const { scheme, meta } of themeColorMetas()) {
    if (choice === "system") {
      meta.media = SCHEME_MEDIA[scheme]
    } else {
      meta.media = choice === scheme ? "all" : "not all"
    }
  }
}
