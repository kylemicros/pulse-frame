import { cn } from "cn"
import { useState } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { GuidedRunPage } from "@/features/guided-capture"
import { MonitorPage } from "@/features/monitor"

type PageTab = "live" | "guided"

const TAB_CLASS =
  "h-auto min-h-11 rounded-md px-4 py-2 text-sm font-semibold text-(--ds-muted) focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-(--ds-count) focus-visible:ring-0 data-active:border-(--ds-edge) data-active:bg-(--ds-surface) data-active:font-bold data-active:text-(--ds-text) dark:text-(--ds-muted) dark:data-active:border-(--ds-edge) dark:data-active:bg-(--ds-surface) dark:data-active:text-(--ds-text)"

function App() {
  const [page, setPage] = useState<PageTab>("live")
  return (
    <Tabs
      value={page}
      onValueChange={(value) => setPage(value === "guided" ? "guided" : "live")}
      className={cn("min-h-svh gap-0", page === "guided" && "bg-(--ds-bg)")}
    >
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 pt-4">
        {page === "guided" ? <h1 className="font-mono text-lg font-bold">pulse-frame</h1> : null}
        <TabsList
          aria-label="Pages"
          className="ml-auto grid h-auto w-full group-data-horizontal/tabs:h-auto grid-cols-2 gap-1 rounded-lg border border-(--ds-border) bg-(--ds-surface-2) p-1 font-sans sm:w-auto"
        >
          <TabsTrigger value="live" className={TAB_CLASS}>
            Live monitor
          </TabsTrigger>
          <TabsTrigger value="guided" className={TAB_CLASS}>
            Guided run
          </TabsTrigger>
        </TabsList>
      </div>
      <TabsContent value="live" className="text-base/normal">
        <MonitorPage />
      </TabsContent>
      <TabsContent value="guided" keepMounted className="text-base/normal">
        <GuidedRunPage active={page === "guided"} />
      </TabsContent>
    </Tabs>
  )
}

export default App
