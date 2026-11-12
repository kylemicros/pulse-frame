import { useState } from "react"
import { ErrorAlert } from "@/components/error-alert"
import { Button } from "@/components/ui/button"
import { CameraPanel } from "@/features/monitor/components/camera-panel"
import { HeartRatePanel } from "@/features/monitor/components/heart-rate-panel"
import { LinkStatus } from "@/features/monitor/components/link-status"
import { PulsePanel } from "@/features/monitor/components/pulse-panel"
import { QualityPanel } from "@/features/monitor/components/quality-panel"
import { useMonitor } from "@/features/monitor/hooks/use-monitor"

export function MonitorPage() {
  const { state, videoRef, start, stop } = useMonitor()
  const [overlayOn, setOverlayOn] = useState(true)
  const idle = state.phase === "idle"
  return (
    <main className="mx-auto flex min-h-svh w-full max-w-6xl flex-col gap-4 p-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-semibold text-foreground">pulse-frame</h1>
          <LinkStatus phase={state.phase} link={state.link} />
        </div>
        {idle ? (
          <Button size="lg" onClick={start}>
            Start
          </Button>
        ) : (
          <Button size="lg" variant="outline" onClick={stop}>
            Stop
          </Button>
        )}
      </header>
      {state.error === null ? null : <ErrorAlert error={state.error} />}
      {state.notice === null ? null : <ErrorAlert error={state.notice} />}
      <div className="grid gap-4 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <CameraPanel
          videoRef={videoRef}
          phase={state.phase}
          scene={state.scene}
          overlayOn={overlayOn}
          onToggleOverlay={() => setOverlayOn((on) => !on)}
        />
        <div className="flex min-w-0 flex-col gap-4">
          <HeartRatePanel
            phase={state.phase}
            reading={state.reading}
            scene={state.scene}
            latestT={state.latestT}
            acquiringSince={state.acquiringSince}
          />
          <QualityPanel qualityDb={state.reading?.quality_db ?? null} />
          <PulsePanel phase={state.phase} samples={state.samples} />
        </div>
      </div>
    </main>
  )
}
