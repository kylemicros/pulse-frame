import { useCallback, useEffect, useReducer, useRef } from "react"
import { MonitorSession } from "@/features/monitor/lib/monitor-session"
import { initialMonitorState, monitorReducer } from "@/features/monitor/lib/monitor-reducer"

export const NOTICE_SHOWN_MS = 5000

export function useMonitor() {
  const [state, dispatch] = useReducer(monitorReducer, initialMonitorState)
  const videoRef = useRef<HTMLVideoElement>(null)
  const sessionRef = useRef<MonitorSession | null>(null)

  const start = useCallback(() => {
    const video = videoRef.current
    if (video === null || sessionRef.current !== null) {
      return
    }
    dispatch({ type: "start" })
    const session = new MonitorSession(video, (event) => {
      if (event.type === "ended" && sessionRef.current === session) {
        sessionRef.current = null
      }
      dispatch(event)
    })
    sessionRef.current = session
    void session.start()
  }, [])

  const stop = useCallback(() => {
    sessionRef.current?.stop()
  }, [])

  useEffect(() => {
    const release = () => {
      sessionRef.current?.stop()
      sessionRef.current = null
    }
    window.addEventListener("pagehide", release)
    return () => {
      window.removeEventListener("pagehide", release)
      release()
    }
  }, [])

  const noticeId = state.notice?.id ?? null
  useEffect(() => {
    if (noticeId === null) {
      return undefined
    }
    const timer = window.setTimeout(() => dispatch({ type: "notice-expired", id: noticeId }), NOTICE_SHOWN_MS)
    return () => window.clearTimeout(timer)
  }, [noticeId])

  return { state, videoRef, start, stop }
}
