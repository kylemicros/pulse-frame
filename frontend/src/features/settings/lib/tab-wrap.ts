const TAB_STOPS = 'button:not([disabled]):not([tabindex="-1"]), [tabindex="0"]'

export function wrappedTabStop(container: HTMLElement, active: Element | null, backwards: boolean): HTMLElement | null {
  const stops = Array.from(container.querySelectorAll<HTMLElement>(TAB_STOPS))
  const first = stops.at(0)
  const last = stops.at(-1)
  if (first === undefined || last === undefined) {
    return null
  }
  const inside = stops.some((stop) => stop === active)
  if (backwards && (active === first || !inside)) {
    return last
  }
  if (!backwards && (active === last || !inside)) {
    return first
  }
  return null
}
