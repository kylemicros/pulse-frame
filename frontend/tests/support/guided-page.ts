import { expect, type Locator, type Page } from '@playwright/test';
import { SETUP_MIN_FPS } from '../../src/features/guided-capture/lib/setup-check';
import type { Hrv, MockBackend, PatchName } from './mock-backend';
import { pageNow } from './page-helpers';
import { firstMessageAfter, lastFrameReplyT, socketRecords } from './socket-recorder';

type Reading = { bpm: number | null; quality_db: number | null; state: 'acquiring' | 'ok' | 'low_quality' };

type SoundWindow = Window & { soundSpy: { count: number } };

export const STEP_NAMES = ['Get comfy', 'Warm-up', 'Counted', 'Result'] as const;
export type StepName = (typeof STEP_NAMES)[number];

const WARM_UP_MS = 60000;
const COUNTED_MS = 90000;
export const RUN_MS = WARM_UP_MS + COUNTED_MS;

export const DISCLAIMER =
  'For wellness and curiosity only. pulse frame is not a medical device, and its numbers are estimates.';
export const VARIATION_LINE =
  'Both show how much the gap between your beats shifts, in ms (thousandths of a second). Compare them only with your own runs.';
export const OLD_VARIATION_LATER = 'Both variation numbers fill in with a later update.';

export const FRAME_SPACING_MS = 34;
export const LONG_STEP_MS = 100;
export const SLOW_STEP_MS = Math.ceil(2000 / SETUP_MIN_FPS);
const PASS_CHECK_BUDGET_MS = 8000;
const PACE_SLICE_STEPS = 5;
const PAUSE_AHEAD_MS = 100;
const PACED_POLL = { intervals: [5, 10, 20] };

export type SetupProblem = 'noFace' | 'far' | 'behind' | 'dark' | 'bright' | 'slow' | 'moving';
export type SetupRow = 'Distance' | 'Light' | 'Stillness' | 'Camera speed';
type Prompt = { prompt: string; line: string };

export const SETUP_PROMPTS: Record<SetupProblem, Prompt> = {
  noFace: { prompt: "Can't find your face.", line: 'Sit facing the camera so your whole face fits in the oval.' },
  far: {
    prompt: 'Move closer to the camera.',
    line: "You're a bit far away to read. Scoot in until your face fills the oval.",
  },
  behind: {
    prompt: 'There is light behind you.',
    line: 'A bright window or lamp behind you turns your face into a silhouette. Turn so the light hits your face instead.',
  },
  dark: {
    prompt: 'Make the room a little brighter.',
    line: 'Your face is hiding in the shadows. Switch on a lamp or face a window.',
  },
  bright: {
    prompt: 'Ease off the light a little.',
    line: 'Your face is washed out. Back away from the lamp or point it somewhere else.',
  },
  slow: {
    prompt: 'The camera is running slow.',
    line: 'Close other apps using the camera, and add some light. Cameras slow down in the dark.',
  },
  moving: {
    prompt: 'Hold still.',
    line: 'Settle in, then stay put like a statue for a few seconds. Breathing is allowed.',
  },
};

export const SETUP_ORDER: SetupProblem[] = ['noFace', 'far', 'behind', 'dark', 'bright', 'slow', 'moving'];
export const SETUP_ROWS: SetupRow[] = ['Distance', 'Light', 'Stillness', 'Camera speed'];
export const ALL_GOOD_PROMPT = 'All good. Hold that.';
export const BOLD = /^[6-9]00$/;
const CAMERA_CHIP_MIN_WIDTH_PX = 768;
export const START_ANYWAY_SAID = 'You can start anyway now.';

export function startsWith(text: string): RegExp {
  return new RegExp(`^${text.replaceAll(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`)}`);
}

export function wholeText(text: string): RegExp {
  return new RegExp(`${startsWith(text).source}$`);
}

export function guidedPage(page: Page) {
  const main = page.getByRole('main');
  const stepList = page.getByRole('list', { name: 'Capture steps' });
  const steps = stepList.getByRole('listitem');
  const liveReadings = main.getByRole('region', { name: 'Live readings' });
  const video = main.getByLabel('Camera preview');
  const cameraBox = video.locator('xpath=..');
  const setupCheck = main.getByRole('list', { name: 'Setup check' });
  return {
    setupCheck,
    setupRow: (name: SetupRow): Locator => setupCheck.getByRole('listitem').filter({ hasText: name }),
    setupPrompt: main.getByTestId('setup-prompt'),
    cameraBox,
    cameraCue: (text: string): Locator => cameraBox.getByText(text, { exact: true }),
    spoken: (text: string): Locator => main.getByRole('status').filter({ hasText: wholeText(text) }),
    startAnyway: main.getByRole('button', { name: 'Start anyway', exact: true }),
    startAnywayWait: main.getByRole('progressbar', { name: 'Until start anyway shows up' }),
    anywayLine: main.getByText(/^Can't fix it right now\?/),
    main,
    stepList,
    steps,
    step: (name: StepName): Locator => steps.filter({ hasText: name }),
    stepName: (name: StepName): Locator => steps.filter({ hasText: name }).getByText(name, { exact: true }),
    oldStepLine: page.getByText(/^Step \d of 4, /),
    headline: (text: string): Locator => main.getByRole('heading', { name: text, exact: true }),
    start: page.getByRole('button', { name: 'Start', exact: true }),
    stop: page.getByRole('button', { name: 'Stop', exact: true }),
    startAgain: page.getByRole('button', { name: 'Start again', exact: true }),
    lock: main.getByRole('button', { name: 'Stays on this computer', exact: true }),
    lockWords: page.getByText('Stays on this computer', { exact: true }),
    video,
    outlines: main.getByTestId(/^patch-outline-/),
    outline: (name: PatchName): Locator => main.getByTestId(`patch-outline-${name}`),
    warmUpTimer: main.getByRole('timer', { name: 'Time until counting starts' }),
    countedTimer: main.getByRole('timer', { name: 'Time until done' }),
    warmUpBar: main.getByRole('progressbar', { name: 'Warm-up', exact: true }),
    countedBar: main.getByRole('progressbar', { name: 'Counted', exact: true }),
    settleBar: main.getByRole('progressbar', { name: 'Heart rate settling' }),
    liveReadings,
    pulseTrace: main.getByRole('img', { name: /^Pulse trace/ }),
    milestones: main.getByTestId('milestone-status'),
    notEnoughBeats: main.getByText('Not enough beats yet', { exact: true }),
    variationLine: main.getByText(VARIATION_LINE, { exact: true }),
    disclaimer: page.getByRole('contentinfo').getByText(DISCLAIMER, { exact: true }),
    alert: main.getByRole('alert'),
  };
}

export function drawnPrompt(page: Page, text: string): Locator {
  const guided = guidedPage(page);
  const width = page.viewportSize()?.width ?? CAMERA_CHIP_MIN_WIDTH_PX;
  return width >= CAMERA_CHIP_MIN_WIDTH_PX ? guided.cameraCue(text) : guided.setupPrompt.getByText(text, { exact: true });
}

export const CALIBRATION_ROWS = [
  'Face span (px)',
  'Face brightness (0 to 255)',
  'Backlight (% near white)',
  'Frames per second',
] as const;
export const CLEAR_SHARE_ROW = 'Clear share (%)';
export type CalibrationRow = (typeof CALIBRATION_ROWS)[number] | typeof CLEAR_SHARE_ROW;
export const CALIBRATION_NOTE = 'On for ?calibrate. Only on this screen; nothing is sent or stored.';
export const CALIBRATION_FOOT =
  'The first four are the last values before the warm-up. Clear share is how much of the counted part the pulse showed clearly.';

export function calibrationBox(page: Page) {
  const region = page.getByRole('main').getByRole('region', { name: 'Calibration', exact: true });
  const table = region.getByRole('table');
  const row = (label: CalibrationRow): Locator =>
    table.getByRole('row').filter({ has: page.getByRole('rowheader', { name: label, exact: true }) });
  return {
    region,
    table,
    heading: region.getByRole('heading', { name: 'Calibration', exact: true }),
    columnHeaders: table.getByRole('columnheader'),
    rowHeaders: table.getByRole('rowheader'),
    row,
    value: (label: CalibrationRow): Locator => row(label).getByRole('cell').nth(0),
    limit: (label: CalibrationRow): Locator => row(label).getByRole('cell').nth(1),
    check: (label: CalibrationRow): Locator => row(label).getByRole('cell').nth(2),
    phase: (text: 'Live, setup check' | 'This run'): Locator => region.getByText(text, { exact: true }),
    note: region.getByText(CALIBRATION_NOTE, { exact: true }),
    runLine: region.getByText(/^Setup check: /),
    foot: region.getByText(CALIBRATION_FOOT, { exact: true }),
  };
}

export async function openGuidedRun(page: Page, address = '/'): Promise<void> {
  await page.goto(address);
  await expect(guidedPage(page).stepList).toBeVisible();
}

export async function startCheck(page: Page, backend: MockBackend): Promise<void> {
  await openGuidedRun(page);
  await guidedPage(page).start.click();
  await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
}

export async function startRun(page: Page, backend: MockBackend): Promise<void> {
  await page.clock.install();
  await startCheck(page, backend);
  await passSetupCheck(page, backend);
}

export async function pauseClock(page: Page): Promise<void> {
  const frozen = await page.evaluate(() => Date.now());
  await page.clock.setFixedTime(frozen);
  await page.clock.pauseAt(frozen + PAUSE_AHEAD_MS);
  await page.clock.setSystemTime(frozen + PAUSE_AHEAD_MS);
}

async function replyToLatestFrame(page: Page, backend: MockBackend): Promise<void> {
  await expect
    .poll(async () => {
      const [open] = backend.openConnections();
      const latest = open === undefined ? undefined : backend.framesOn(open.id).at(-1);
      if (latest === undefined) {
        return true;
      }
      return (await lastFrameReplyT(page)) === Math.floor(latest.captureMs);
    }, PACED_POLL)
    .toBe(true);
}

export async function paceReplies(page: Page, backend: MockBackend, ms: number, stepMs = FRAME_SPACING_MS): Promise<void> {
  for (let spent = 0; spent < ms; spent += stepMs) {
    await replyToLatestFrame(page, backend);
    const target = backend.frames.length + 1;
    await page.clock.runFor(stepMs);
    await expect
      .poll(() => backend.frames.length >= target || backend.openConnections().length === 0, PACED_POLL)
      .toBe(true);
  }
  await replyToLatestFrame(page, backend);
}

export async function paceUntil(
  page: Page,
  backend: MockBackend,
  shown: Locator,
  budgetMs: number,
  stepMs = FRAME_SPACING_MS,
): Promise<void> {
  let spentMs = 0;
  while (!(await shown.isVisible())) {
    expect(spentMs, `page time paced waiting for ${shown.toString()}`).toBeLessThan(budgetMs);
    await paceReplies(page, backend, stepMs * PACE_SLICE_STEPS, stepMs);
    spentMs += stepMs * PACE_SLICE_STEPS;
  }
}

export async function paceUntilPageTime(
  page: Page,
  backend: MockBackend,
  at: number,
  stepMs = FRAME_SPACING_MS,
): Promise<void> {
  const left = at - (await pageNow(page));
  if (left > 0) {
    await paceReplies(page, backend, left, stepMs);
  }
}

export async function passSetupCheck(page: Page, backend: MockBackend): Promise<void> {
  const guided = guidedPage(page);
  if (await guided.warmUpTimer.isVisible()) {
    return;
  }
  await pauseClock(page);
  await paceUntil(page, backend, guided.warmUpTimer, PASS_CHECK_BUDGET_MS);
  await page.clock.resume();
}

type Said = { at: number; text: string };

type SaidWindow = Window & { announcements: Said[]; textOf: Record<string, Said[]> };

export async function recordAnnouncements(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const said: Said[] = [];
    Object.defineProperty(globalThis, 'announcements', { value: said });
    const last = new WeakMap<Element, string>();
    const liveRoles = new Set(['status', 'alert', 'log', 'marquee']);
    const isLive = (element: Element): boolean => {
      const live = element.getAttribute('aria-live');
      if (live !== null) {
        return live !== 'off';
      }
      const role = element.getAttribute('role');
      return role === null ? element.tagName === 'OUTPUT' : liveRoles.has(role);
    };
    const scan = () => {
      for (const element of document.querySelectorAll('[aria-live], [role], output')) {
        if (!isLive(element)) {
          continue;
        }
        const text = (element.textContent ?? '').replaceAll(/\s+/g, ' ').trim();
        if (last.get(element) !== text) {
          last.set(element, text);
          if (text !== '') {
            said.push({ at: performance.now(), text });
          }
        }
      }
    };
    new MutationObserver(scan).observe(document, { subtree: true, childList: true, characterData: true });
  });
}

export function announcements(page: Page): Promise<Said[]> {
  return page.evaluate(() => [...(globalThis as unknown as SaidWindow).announcements]);
}

export async function recordTextOf(page: Page, testId: string): Promise<void> {
  await page.addInitScript((id) => {
    const host = globalThis as unknown as SaidWindow;
    if (host.textOf === undefined) {
      Object.defineProperty(globalThis, 'textOf', { value: {} });
    }
    const changes: Said[] = [];
    host.textOf[id] = changes;
    let last = '';
    new MutationObserver(() => {
      const element = document.querySelector(`[data-testid="${id}"]`);
      const text = (element?.textContent ?? '').replaceAll(/\s+/g, ' ').trim();
      if (text !== last) {
        last = text;
        changes.push({ at: performance.now(), text });
      }
    }).observe(document, { subtree: true, childList: true, characterData: true });
  }, testId);
}

export function recordedTextOf(page: Page, testId: string): Promise<Said[]> {
  return page.evaluate((id) => [...(globalThis as unknown as SaidWindow).textOf[id]], testId);
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

export async function expectQuietRef(scope: Locator, message: string, code: string): Promise<void> {
  const said = scope.getByText(message);
  const ref = scope.getByText(`Ref: ${code}`, { exact: true });
  await expect(said).toBeVisible();
  await expect(ref).toBeVisible();
  expect(await said.innerText()).not.toMatch(CODED_TEXT);
  const saidBox = await said.boundingBox();
  const refBox = await ref.boundingBox();
  expect(saidBox).not.toBeNull();
  expect(refBox).not.toBeNull();
  expect(refBox?.y ?? 0).toBeGreaterThanOrEqual((saidBox?.y ?? 0) + (saidBox?.height ?? 0) - 1);
  const shownText = await scope.innerText();
  expect(shownText.split(code).length - 1, `times ${code} shows on the page`).toBe(1);
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

export async function setHrvAndConfirm(page: Page, backend: MockBackend, fields: Hrv): Promise<void> {
  const since = await pageNow(page);
  backend.setHrv(fields);
  const wanted = Object.entries(fields);
  await expect
    .poll(async () =>
      firstMessageAfter(
        await socketRecords(page),
        since,
        (message) => message.type === 'hrv' && wanted.every(([key, value]) => message[key] === value),
      ),
    )
    .not.toBeNull();
}

export type TermLabel = 'Beat to beat variation' | 'Overall rhythm variation' | 'Heart rate';

export function termLines(scope: Locator, label: TermLabel): Promise<string[]> {
  return scope.evaluate((root, term) => {
    const found = Array.from(root.querySelectorAll('dt')).filter((element) => element.textContent?.trim() === term);
    if (found.length !== 1) {
      return [`${found.length} terms named ${term}`];
    }
    const lines: string[] = [];
    for (let node = found[0].nextElementSibling; node !== null && node.tagName === 'DD'; node = node.nextElementSibling) {
      lines.push((node as HTMLElement).innerText.replaceAll(/\s+/g, ' ').trim());
    }
    return lines;
  }, label);
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
      await expect(step).toContainText('done', { ignoreCase: true });
    }
    await expect(step).not.toContainText('Stopped');
  }
}

export async function expectStoppedStep(page: Page, stopped: StepName): Promise<void> {
  const guided = guidedPage(page);
  await expect(guided.steps).toHaveCount(4);
  const index = STEP_NAMES.indexOf(stopped);
  for (const [position, name] of STEP_NAMES.entries()) {
    const step = guided.step(name);
    await expect(step).not.toContainText('Now');
    await expect(step).not.toHaveAttribute('aria-current', 'step');
    if (position === index) {
      await expect(step).toContainText('Stopped');
    } else {
      await expect(step).not.toContainText('Stopped');
    }
    if (position < index) {
      await expect(step).toContainText('done', { ignoreCase: true });
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

type CountChange = { at: number; count: number };

type CountWindow = Window & { outlineCounts: CountChange[] };

export async function watchOutlineCount(page: Page): Promise<void> {
  await guidedPage(page).main.evaluate((root) => {
    const count = () => root.querySelectorAll('[data-testid^="patch-outline-"]').length;
    const changes: CountChange[] = [{ at: performance.now(), count: count() }];
    Object.defineProperty(globalThis, 'outlineCounts', { value: changes, configurable: true });
    new MutationObserver(() => {
      const now = count();
      if (changes.at(-1)?.count !== now) {
        changes.push({ at: performance.now(), count: now });
      }
    }).observe(root, { childList: true, subtree: true });
  });
}

export function outlineCountChanges(page: Page): Promise<CountChange[]> {
  return page.evaluate(() => [...(globalThis as unknown as CountWindow).outlineCounts]);
}

export function fontFamily(locator: Locator): Promise<string> {
  return locator.evaluate((element) => getComputedStyle(element).fontFamily);
}
