import { countdownSeconds } from "@/features/guided-capture/lib/run-plan"
import { SETUP_ALL_GOOD_MS, type SetupCheck } from "@/features/guided-capture/lib/setup-check"
import { allGoodLine, SETUP_LEAD, SETUP_PROMPTS, setupPromptText } from "@/features/guided-capture/lib/setup-copy"

type SetupCheckPromptProps = {
  check: SetupCheck
  now: number
}

function allGoodSeconds(check: SetupCheck, now: number): number {
  return countdownSeconds(SETUP_ALL_GOOD_MS, check.goodSince === null ? 0 : now - check.goodSince)
}

export function SetupCheckPrompt({ check, now }: SetupCheckPromptProps) {
  const { shown } = check
  const allGood = shown === "allGood"
  const prompt = setupPromptText(check)
  const line = shown === null ? "" : allGood ? allGoodLine(allGoodSeconds(check, now)) : SETUP_PROMPTS[shown].line
  return (
    <>
      {allGood ? null : <p>{SETUP_LEAD}</p>}
      {prompt === null ? null : (
        <p
          data-testid="setup-prompt"
          className="rounded-md border border-l-4 border-(--ds-edge) border-l-(--ds-count) bg-(--ds-surface) px-3 py-2.5"
        >
          <strong className="block text-lg">{prompt}</strong> {line}
        </p>
      )}
    </>
  )
}
