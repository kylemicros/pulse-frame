import type { Phase } from "@/features/monitor/types"
import type { LinkStatus as Link } from "@/lib/socket/stream-client"

const LINK_TEXT: Record<Link, string> = {
  connecting: "Knocking on the backend...",
  live: "Streaming to the backend on this machine.",
  busy: "Another tab has the backend. Close the other tab or press Stop there; this page keeps waiting.",
  unreachable: "Backend not reachable. Retrying.",
}

type LinkStatusProps = {
  phase: Phase
  link: Link | null
}

export function LinkStatus({ phase, link }: LinkStatusProps) {
  let text = "Camera off."
  if (phase === "starting") {
    text = "Waking up the camera..."
  } else if (phase === "running" && link !== null) {
    text = LINK_TEXT[link]
  }
  return (
    <output className="block text-sm text-muted-foreground">{text}</output>
  )
}
