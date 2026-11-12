import { useEffect, useState } from "react"
import { HOLD_MS } from "@/features/monitor/hooks/use-held-value"
import type { BpmMessage } from "@/lib/socket/messages"

export type ShownBpm = { value: number | null; dimmed: boolean }

type Hold = { reading: BpmMessage | null; lastOk: number | null; held: number | null }

function okBpm(reading: BpmMessage | null): number | null {
  return reading !== null && reading.state === "ok" ? reading.bpm : null
}

export function useShownBpm(reading: BpmMessage | null): ShownBpm {
  const [hold, setHold] = useState<Hold>({ reading, lastOk: okBpm(reading), held: null })

  let current = hold
  if (hold.reading !== reading) {
    const ok = okBpm(reading)
    current = { reading, lastOk: ok, held: ok === null && reading !== null ? hold.lastOk : null }
    setHold(current)
  }

  useEffect(() => {
    if (hold.held === null) {
      return undefined
    }
    const timer = window.setTimeout(
      () => setHold((latest) => (latest === hold ? { ...latest, held: null } : latest)),
      HOLD_MS,
    )
    return () => window.clearTimeout(timer)
  }, [hold])

  if (current.lastOk !== null) {
    return { value: current.lastOk, dimmed: false }
  }
  return { value: current.held, dimmed: current.held !== null }
}
