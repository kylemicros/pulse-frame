import { GuidedRunPage } from "@/features/guided-capture"

function App() {
  return (
    <div className="min-h-svh bg-(--ds-bg) text-base/normal">
      <div className="mx-auto flex min-h-11 w-full max-w-6xl items-center px-4 pt-4">
        <h1 className="font-mono text-lg font-bold text-(--ds-text)">pulse-frame</h1>
      </div>
      <GuidedRunPage />
    </div>
  )
}

export default App
