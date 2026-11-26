import { useCallback, useEffect, useEffectEvent, useReducer, useRef, useState } from "react"
import { Chime } from "@/features/guided-capture/lib/chime"
import { guidedReducer, initialGuidedState } from "@/features/guided-capture/lib/guided-reducer"
import { MonitorSession } from "@/features/guided-capture/lib/monitor-session"
import { PAGE_HIDDEN, SOCKET_BUSY } from "@/features/guided-capture/lib/run-copy"
import { runStage, tabTitle, TICK_MS } from "@/features/guided-capture/lib/run-plan"
import { SOCKET_UNAVAILABLE } from "@/lib/socket/socket-errors"

const NOTICE_SHOWN_MS = 5000

export function useGuidedRun() {
  const [state, dispatch] = useReducer(guidedReducer, initialGuidedState)
  const [chimeOn, setChimeOn] = useState(true)
  const [chime] = useState(() => new Chime())
  const [pageTitle] = useState(() => document.title)
  const videoRef = useRef<HTMLVideoElement>(null)
  const sessionRef = useRef<MonitorSession | null>(null)
  const stage = runStage(state)
  const title = tabTitle(state)

  const start = useCallback(() => {
    const video = videoRef.current
    if (video === null || sessionRef.current !== null) {
      return
    }
    if (chimeOn) {
      chime.prepare()
    } else {
      chime.close()
    }
    dispatch({ type: "start" })
    const session = new MonitorSession(video, (event) => {
      if (event.type === "ended" && sessionRef.current === session) {
        sessionRef.current = null
      }
      dispatch({ type: "session", event, at: performance.now() })
      if (event.type === "link" && (event.status === "busy" || event.status === "unreachable")) {
        dispatch({ type: "halt", error: event.status === "busy" ? SOCKET_BUSY : SOCKET_UNAVAILABLE })
        queueMicrotask(() => session.stop())
      }
    })
    sessionRef.current = session
    void session.start()
  }, [chime, chimeOn])

  const stop = useCallback(() => {
    sessionRef.current?.stop()
  }, [])

  const startAnyway = useCallback(() => dispatch({ type: "start-anyway", at: performance.now() }), [])

  const toggleChime = useCallback(() => setChimeOn((on) => !on), [])

  useEffect(() => {
    const leaveWhenHidden = () => {
      const session = sessionRef.current
      if (document.visibilityState === "hidden" && session !== null) {
        dispatch({ type: "halt", error: PAGE_HIDDEN })
        session.stop()
      }
    }
    const release = () => {
      sessionRef.current?.stop()
      sessionRef.current = null
      chime.close()
    }
    document.addEventListener("visibilitychange", leaveWhenHidden)
    window.addEventListener("pagehide", release)
    return () => {
      document.removeEventListener("visibilitychange", leaveWhenHidden)
      window.removeEventListener("pagehide", release)
      release()
      chime.close()
    }
  }, [chime])

  useEffect(() => {
    if (state.status === "running") {
      sessionRef.current?.endSetupCheck()
    }
  }, [state.status])

  useEffect(() => {
    if (state.status !== "running" && state.status !== "checking") {
      return undefined
    }
    const timer = globalThis.setInterval(() => dispatch({ type: "tick", at: performance.now() }), TICK_MS)
    return () => globalThis.clearInterval(timer)
  }, [state.status])

  useEffect(() => {
    if (state.status === "done") {
      sessionRef.current?.stop()
    }
    if (state.status === "stopped" || state.status === "idle") {
      chime.close()
    }
  }, [state.status, chime])

  const cueStage = useEffectEvent((reached: typeof stage) => {
    if (!chimeOn) {
      return
    }
    if (reached === "counted") {
      chime.play()
    } else if (reached === "result") {
      chime.play("close")
    }
  })

  useEffect(() => {
    cueStage(stage)
  }, [stage])

  useEffect(() => {
    document.title = title ?? pageTitle
    return () => {
      document.title = pageTitle
    }
  }, [title, pageTitle])

  const noticeId = state.monitor.notice?.id ?? null
  useEffect(() => {
    if (noticeId === null) {
      return undefined
    }
    const timer = globalThis.setTimeout(() => dispatch({ type: "notice-expired", id: noticeId }), NOTICE_SHOWN_MS)
    return () => globalThis.clearTimeout(timer)
  }, [noticeId])

  return { state, stage, videoRef, start, stop, startAnyway, chimeOn, toggleChime }
}
