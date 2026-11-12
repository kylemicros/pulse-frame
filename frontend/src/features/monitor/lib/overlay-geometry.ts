import type { Point } from "@/lib/socket/messages"

function clampUnit(value: number): number {
  return Math.min(1, Math.max(0, value))
}

export function overlayPoints(outline: readonly Point[], mirrored: boolean): string {
  return outline
    .map(([x, y]) => {
      const clampedX = clampUnit(x)
      return `${mirrored ? 1 - clampedX : clampedX},${clampUnit(y)}`
    })
    .join(" ")
}
