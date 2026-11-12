export type QualityBand = "weak" | "fair" | "good"

export const FAIR_FROM_DB = 3
export const GOOD_FROM_DB = 8

export function qualityBand(qualityDb: number): QualityBand {
  if (qualityDb < FAIR_FROM_DB) {
    return "weak"
  }
  return qualityDb < GOOD_FROM_DB ? "fair" : "good"
}
