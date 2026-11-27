import { countdownSeconds } from "@/features/guided-capture/lib/run-plan"
import { SETUP_ALL_GOOD_MS, type SetupCheck } from "@/features/guided-capture/lib/setup-check"
import { allGoodLine, SETUP_PROMPTS, setupPromptText } from "@/features/guided-capture/lib/setup-copy"

type SetupPromptBoxProps = {
  check: SetupCheck
  now: number
  promptOnCamera: boolean
}

function allGoodSeconds(check: SetupCheck, now: number): number {
  return countdownSeconds(SETUP_ALL_GOOD_MS, check.goodSince === null ? 0 : now - check.goodSince)
}

export function SetupPromptBox({ check, now, promptOnCamera }: SetupPromptBoxProps) {
  const { shown } = check
  const prompt = setupPromptText(check)
  if (shown === null || prompt === null) {
    return null
  }
  const line = shown === "allGood" ? allGoodLine(allGoodSeconds(check, now)) : SETUP_PROMPTS[shown].line
  return (
    <p
      data-testid="setup-prompt"
      className="rounded-md border border-l-4 border-(--ds-edge) border-l-(--ds-count) bg-(--ds-surface) px-3 py-2.5"
    >
      <strong className={promptOnCamera ? "sr-only" : "block text-lg"}>{prompt}</strong> {line}
    </p>
  )
}
