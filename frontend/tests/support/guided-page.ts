import { expect, type Locator, type Page } from '@playwright/test';
import type { MockBackend } from './mock-backend';
import { pageNow } from './monitor-page';
import { firstMessageAfter, socketRecords } from './socket-recorder';

type Reading = { bpm: number | null; quality_db: number | null; state: 'acquiring' | 'ok' | 'low_quality' };

type SoundWindow = Window & { soundSpy: { count: number } };

const STEP_NAMES = ['Get comfy', 'Warm-up', 'Counted', 'Result'] as const;
type StepName = (typeof STEP_NAMES)[number];

const WARM_UP_MS = 60000;
const COUNTED_MS = 90000;
export const RUN_MS = WARM_UP_MS + COUNTED_MS;

const DISCLAIMER =
  'For wellness and curiosity only. pulse-frame is not a medical device, and its numbers are estimates.';
const VARIATION_LATER = 'Both variation numbers fill in with a later update.';

export function guidedPage(page: Page) {
  const panel = page.getByRole('tabpanel', { name: 'Guided run' });
  const steps = panel.getByRole('list', { name: 'Capture steps' }).getByRole('listitem');
  const liveReadings = panel.getByRole('region', { name: 'Live readings' });
  return {
    liveTab: page.getByRole('tab', { name: 'Live monitor', exact: true }),
    guidedTab: page.getByRole('tab', { name: 'Guided run', exact: true }),
    panel,
    steps,
    step: (name: StepName): Locator => steps.filter({ hasText: name }),
    phaseLine: (text: string): Locator => panel.getByText(text, { exact: true }),
    headline: (text: string): Locator => panel.getByRole('heading', { name: text, exact: true }),
    start: panel.getByRole('button', { name: 'Start', exact: true }),
    stop: panel.getByRole('button', { name: 'Stop', exact: true }),
    startAgain: panel.getByRole('button', { name: 'Start again', exact: true }),
    chime: panel.getByRole('button', { name: /^Chime at start and end/ }),
    warmUpTimer: panel.getByRole('timer', { name: 'Time until counting starts' }),
    countedTimer: panel.getByRole('timer', { name: 'Time until done' }),
    warmUpBar: panel.getByRole('progressbar', { name: 'Warm-up', exact: true }),
    countedBar: panel.getByRole('progressbar', { name: 'Counted', exact: true }),
    settleBar: panel.getByRole('progressbar', { name: 'Heart rate settling' }),
    liveReadings,
    pulseTrace: panel.getByRole('img', { name: /^Pulse trace/ }),
    milestones: panel.getByTestId('milestone-status'),
    notEnoughBeats: panel.getByText('Not enough beats yet', { exact: true }),
    variationLater: panel.getByText(VARIATION_LATER, { exact: true }),
    disclaimer: panel.getByText(DISCLAIMER, { exact: true }),
    alert: panel.getByRole('alert'),
  };
}

export async function openGuidedRun(page: Page): Promise<void> {
  await page.goto('/');
  await guidedPage(page).guidedTab.click();
  await expect(guidedPage(page).panel).toBeVisible();
}

export async function startRun(page: Page, backend: MockBackend): Promise<void> {
  await openGuidedRun(page);
  await guidedPage(page).start.click();
  await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
}

async function nextFrameOrClosed(backend: MockBackend): Promise<void> {
  const target = backend.frames.length + 1;
  await expect
    .poll(() => backend.frames.length >= target || backend.openConnections().length === 0)
    .toBe(true);
}

export async function advanceRun(page: Page, backend: MockBackend, ms: number, sliceMs = 5000): Promise<void> {
  let left = ms;
  while (left > 0) {
    const slice = Math.min(sliceMs, left);
    await page.clock.runFor(slice);
    left -= slice;
    await nextFrameOrClosed(backend);
  }
}

export async function advanceRunUntil(
  page: Page,
  backend: MockBackend,
  shown: Locator,
  sliceMs = 5000,
  budgetMs = RUN_MS + 10000,
): Promise<void> {
  let spentMs = 0;
  while (!(await shown.isVisible())) {
    expect(spentMs, `page time spent waiting for ${shown.toString()}`).toBeLessThan(budgetMs);
    await page.clock.runFor(sliceMs);
    spentMs += sliceMs;
    await nextFrameOrClosed(backend);
  }
}

export async function expectQuietRef(panel: Locator, message: string, code: string): Promise<void> {
  const said = panel.getByText(message);
  const ref = panel.getByText(`Ref: ${code}`, { exact: true });
  await expect(said).toBeVisible();
  await expect(ref).toBeVisible();
  expect(await said.innerText()).not.toMatch(CODED_TEXT);
  const saidBox = await said.boundingBox();
  const refBox = await ref.boundingBox();
  expect(saidBox).not.toBeNull();
  expect(refBox).not.toBeNull();
  expect(refBox?.y ?? 0).toBeGreaterThanOrEqual((saidBox?.y ?? 0) + (saidBox?.height ?? 0) - 1);
  const panelText = await panel.innerText();
  expect(panelText.split(code).length - 1, `times ${code} shows in the panel`).toBe(1);
}

const CODED_TEXT = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/;

export function liveRegionsIn(scope: Locator): Promise<string[]> {
  return scope.evaluate((root) => {
    const liveRoles = new Set(['status', 'alert', 'log', 'marquee']);
    return Array.from(root.querySelectorAll('*'))
      .filter((element) => {
        const live = element.getAttribute('aria-live');
        if (live !== null) {
          return live !== 'off';
        }
        const role = element.getAttribute('role');
        return role === null ? element.tagName === 'OUTPUT' : liveRoles.has(role);
      })
      .map((element) => element.getAttribute('data-testid') ?? element.tagName.toLowerCase());
  });
}

export const RUN_STOPPED_TEXT = 'Run stopped. Press Start again for a fresh run.';
export const FACE_A_WINDOW_CUE = 'Face a window so the light is even.';

export async function pushAndConfirm(page: Page, backend: MockBackend, reading: Reading): Promise<void> {
  const since = await pageNow(page);
  backend.pushReading(reading);
  await expect
    .poll(async () =>
      firstMessageAfter(
        await socketRecords(page),
        since,
        (message) => message.type === 'bpm' && message.state === reading.state && message.bpm === reading.bpm,
      ),
    )
    .not.toBeNull();
}

export async function expectCurrentStep(page: Page, current: StepName): Promise<void> {
  const guided = guidedPage(page);
  await expect(guided.steps).toHaveCount(4);
  const index = STEP_NAMES.indexOf(current);
  for (const [position, name] of STEP_NAMES.entries()) {
    const step = guided.step(name);
    if (position === index) {
      await expect(step).toHaveAttribute('aria-current', 'step');
      await expect(step).toContainText('Now');
    } else {
      await expect(step).not.toHaveAttribute('aria-current', 'step');
      await expect(step).not.toContainText('Now');
    }
    if (position < index) {
      await expect(step).toContainText('Done');
    }
  }
}

export async function valueNow(bar: Locator): Promise<number> {
  return Number(await bar.getAttribute('aria-valuenow'));
}

export async function timerSeconds(timer: Locator): Promise<number> {
  const match = /^(\d+) s$/.exec((await timer.innerText()).trim());
  expect(match, 'the countdown reads as whole seconds, like "48 s"').not.toBeNull();
  return Number(match?.[1]);
}

export async function spyOnSounds(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const spy = { count: 0 };
    Object.defineProperty(globalThis, 'soundSpy', { value: spy });
    const start = AudioScheduledSourceNode.prototype.start;
    AudioScheduledSourceNode.prototype.start = function startAndCount(
      this: AudioScheduledSourceNode,
      ...args: Parameters<AudioScheduledSourceNode['start']>
    ) {
      spy.count += 1;
      return start.apply(this, args);
    };
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function playAndCount(this: HTMLMediaElement) {
      if (this instanceof HTMLAudioElement) {
        spy.count += 1;
      }
      return play.call(this);
    };
  });
}

export function soundsPlayed(page: Page): Promise<number> {
  return page.evaluate(() => (globalThis as unknown as SoundWindow).soundSpy.count);
}

type AudioCloseWindow = Window & { audioCloseSpy: { count: number } };

export async function spyOnAudioClose(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const spy = { count: 0 };
    Object.defineProperty(globalThis, 'audioCloseSpy', { value: spy });
    const close = AudioContext.prototype.close;
    AudioContext.prototype.close = function closeAndCount(this: AudioContext) {
      spy.count += 1;
      return close.call(this);
    };
  });
}

export function audioContextsClosed(page: Page): Promise<number> {
  return page.evaluate(() => (globalThis as unknown as AudioCloseWindow).audioCloseSpy.count);
}

export async function breakAudioContext(page: Page): Promise<void> {
  await page.addInitScript((reason) => {
    Object.defineProperty(globalThis, 'AudioContext', {
      value: function refuseAudio(): never {
        throw new DOMException(reason, 'NotSupportedError');
      },
      configurable: true,
      writable: true,
    });
  }, 'Web Audio is not available here.');
}

export async function advanceStalledRunUntil(page: Page, shown: Locator, sliceMs = 5000): Promise<void> {
  let spentMs = 0;
  while (!(await shown.isVisible())) {
    expect(spentMs, `page time spent waiting for ${shown.toString()}`).toBeLessThan(RUN_MS + 10000);
    await page.clock.runFor(sliceMs);
    spentMs += sliceMs;
  }
}

export function fontFamily(locator: Locator): Promise<string> {
  return locator.evaluate((element) => getComputedStyle(element).fontFamily);
}
