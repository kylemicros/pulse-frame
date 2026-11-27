import { SetupPromptBox } from "@/features/guided-capture/components/setup-prompt-box"
import type { SetupCheck } from "@/features/guided-capture/lib/setup-check"
import { SETUP_LEAD } from "@/features/guided-capture/lib/setup-copy"

type SetupCheckPromptProps = {
  check: SetupCheck
  now: number
  cuesUnderCamera: boolean
}

export function SetupCheckPrompt({ check, now, cuesUnderCamera }: SetupCheckPromptProps) {
  return (
    <>
      {check.shown === "allGood" ? null : <p>{SETUP_LEAD}</p>}
      {cuesUnderCamera ? null : <SetupPromptBox check={check} now={now} promptOnCamera />}
    </>
  )
}
