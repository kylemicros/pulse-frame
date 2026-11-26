import { GuidedRunPage } from "@/features/guided-capture"

function App() {
  return (
    <div className="min-h-svh bg-(--ds-bg) text-base/normal">
      <header className="mx-auto flex min-h-11 w-full max-w-6xl items-center gap-2.5 px-4 pt-4">
        <svg
          viewBox="0 0 32 32"
          className="size-8 shrink-0"
          aria-hidden="true"
          focusable="false"
        >
          <path
            fill="none"
            stroke="#0072b2"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="4"
            d="M3 25q8-32 16 0"
          />
          <circle cx="26.5" cy="23.5" r="3.5" fill="#d55e00" />
        </svg>
        <h1 className="font-mono text-lg font-bold text-(--ds-text)">pulse-frame</h1>
      </header>
      <GuidedRunPage />
    </div>
  )
}

export default App
