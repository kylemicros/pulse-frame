export const RETRY_BASE_MS = 250
export const RETRY_CAP_MS = 8000

export function retryDelay(attempt: number, random: () => number = Math.random): number {
  const growing = RETRY_BASE_MS * 2 ** attempt
  return Math.min(growing, RETRY_CAP_MS) + random() * RETRY_BASE_MS
}
