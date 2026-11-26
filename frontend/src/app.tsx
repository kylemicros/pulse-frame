import { GuidedRunPage } from "@/features/guided-capture"

const DISCLAIMER =
  "For wellness and curiosity only. pulse-frame is not a medical device, and its numbers are estimates."
const LICENCE_LINE = "© 2026 kylemicros. MIT licence."

function App() {
  return (
    <div className="flex min-h-dvh flex-col bg-(--ds-bg) pb-(--phone-bar-space) text-base/normal md:pb-0 lg:h-dvh">
      <header className="mx-auto flex min-h-11 w-full max-w-6xl flex-none items-center gap-2.5 px-safe-4 pt-4 lg:max-w-none lg:px-safe-6">
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
      <footer className="mx-auto flex w-full max-w-6xl flex-none flex-wrap justify-between gap-x-6 gap-y-0.5 px-safe-4 py-2 font-sans text-sm text-(--ds-muted) lg:max-w-none lg:border-t lg:border-(--ds-border) lg:px-safe-6 lg:py-1.5">
        <p>{DISCLAIMER}</p>
        <p>{LICENCE_LINE}</p>
      </footer>
    </div>
  )
}

export default App
