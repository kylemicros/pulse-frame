import { expect, test, type Locator, type Page } from '@playwright/test';
import { SETUP_MIN_FACE_SPAN_PX } from '../../../src/features/guided-capture/lib/setup-check';
import {
  ALL_GOOD_PROMPT,
  announcements,
  expectCurrentStep,
  FRAME_SPACING_MS,
  guidedPage,
  LONG_STEP_MS,
  openGuidedRun,
  paceReplies,
  paceUntil,
  paceUntilPageTime,
  pauseClock,
  recordAnnouncements,
  recordedTextOf,
  recordTextOf,
  RUN_STOPPED_TEXT,
  SETUP_ORDER,
  SETUP_PROMPTS,
  SETUP_ROWS,
  SLOW_STEP_MS,
  START_ANYWAY_SAID,
  startCheck,
  startsWith,
  timerSeconds,
  type SetupProblem,
  type SetupRow,
} from '../../support/guided-page';
import { installLitCamera, showLight, type Light } from '../../support/lit-camera';
import { faceScene, faceWithSpan, MockBackend, NO_FACE_SCENE, type Scene } from '../../support/mock-backend';
import { boxOf, endVideoTracks, failFrameEncoding, pageNow, spyOnCamera } from '../../support/page-helpers';
import { socketRecords } from '../../support/socket-recorder';

type PixelReadWindow = Window & { pixelReads: { count: number } };

async function countPixelReads(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const spy = { count: 0 };
    Object.defineProperty(globalThis, 'pixelReads', { value: spy });
    const read = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function readAndCount(
      this: CanvasRenderingContext2D,
      ...args: Parameters<CanvasRenderingContext2D['getImageData']>
    ) {
      spy.count += 1;
      return read.apply(this, args);
    };
  });
}

function pixelReads(page: Page): Promise<number> {
  return page.evaluate(() => (globalThis as unknown as PixelReadWindow).pixelReads.count);
}

async function frameRepliesSeen(page: Page): Promise<number> {
  const records = await socketRecords(page);
  return records
    .flatMap((record) => record.messages)
    .filter((message) => (JSON.parse(message.text) as { type?: string }).type === 'frame').length;
}

const PROMPT_HOLD_MS = 2000;
const ALL_GOOD_MS = 3000;
const START_ANYWAY_MS = 15000;
const SETTLE_MS = 2 * PROMPT_HOLD_MS + 1000;
const FAR_SPAN_PX = SETUP_MIN_FACE_SPAN_PX / 2;
const BOLD = /^[6-9]00$/;
const CODED_TEXT = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/;

type Setup = { scene: Scene; light: Light; stepMs: number };

const GOOD: Setup = { scene: faceScene(), light: 'even', stepMs: FRAME_SPACING_MS };

const FAR = faceWithSpan(FAR_SPAN_PX);
const MOVING = faceScene({ moving: true });

const ONE_PROBLEM: Record<SetupProblem, { why: string; setup: Partial<Setup>; notYet: SetupRow[] }> = {
  noFace: { why: 'no face is found', setup: { scene: NO_FACE_SCENE }, notYet: ['Distance', 'Light'] },
  far: { why: 'the cheek to cheek span is under the face size threshold', setup: { scene: FAR }, notYet: ['Distance'] },
  behind: { why: 'the ring around the face is mostly near white', setup: { light: 'behind' }, notYet: ['Light'] },
  dark: { why: 'the face box is darker than the brightness band', setup: { light: 'dark' }, notYet: ['Light'] },
  bright: { why: 'the face box is brighter than the brightness band', setup: { light: 'bright' }, notYet: ['Light'] },
  slow: { why: 'replies come in under the frame rate threshold', setup: { stepMs: SLOW_STEP_MS }, notYet: ['Camera speed'] },
  moving: { why: 'the frame replies say the face is moving', setup: { scene: MOVING }, notYet: ['Stillness'] },
};

const TWO_PROBLEMS: Array<{ first: SetupProblem; second: SetupProblem; setup: Partial<Setup>; notYet: SetupRow[] }> = [
  { first: 'noFace', second: 'dark', setup: { scene: NO_FACE_SCENE, light: 'dark' }, notYet: ['Distance', 'Light'] },
  { first: 'far', second: 'behind', setup: { scene: FAR, light: 'behind' }, notYet: ['Distance', 'Light'] },
  { first: 'behind', second: 'dark', setup: { light: 'behind-dark' }, notYet: ['Light'] },
  { first: 'dark', second: 'slow', setup: { light: 'dark', stepMs: SLOW_STEP_MS }, notYet: ['Light', 'Camera speed'] },
  { first: 'bright', second: 'moving', setup: { light: 'bright', scene: MOVING }, notYet: ['Light', 'Stillness'] },
  { first: 'far', second: 'moving', setup: { scene: faceWithSpan(FAR_SPAN_PX, { moving: true }) }, notYet: ['Distance', 'Stillness'] },
  { first: 'slow', second: 'moving', setup: { stepMs: SLOW_STEP_MS, scene: MOVING }, notYet: ['Camera speed', 'Stillness'] },
];

async function openCheck(page: Page, change: Partial<Setup> = {}): Promise<{ backend: MockBackend; setup: Setup }> {
  const setup = { ...GOOD, ...change };
  await installLitCamera(page, setup.light);
  await recordAnnouncements(page);
  await recordTextOf(page, 'setup-prompt');
  const backend = await MockBackend.attach(page);
  backend.setScene(setup.scene);
  await page.clock.install();
  await startCheck(page, backend);
  await pauseClock(page);
  return { backend, setup };
}

async function expectRows(page: Page, notYet: SetupRow[]): Promise<void> {
  const guided = guidedPage(page);
  await expect(guided.setupCheck.getByRole('listitem')).toHaveCount(SETUP_ROWS.length);
  for (const row of SETUP_ROWS) {
    const failing = notYet.includes(row);
    const item = guided.setupRow(row);
    await expect(item.getByText(failing ? 'Not yet' : 'Good', { exact: true }), `${row} row word`).toBeVisible();
    await expect(item.getByText(failing ? 'Good' : 'Not yet', { exact: true }), `${row} row word`).toHaveCount(0);
  }
}

function hiddenFromScreenReaders(locator: Locator): Promise<boolean> {
  return locator.evaluate((element) => element.closest('[aria-hidden="true"]') !== null);
}

async function expectOnlyPrompt(page: Page, problem: SetupProblem): Promise<void> {
  const guided = guidedPage(page);
  const { prompt, line } = SETUP_PROMPTS[problem];
  await expect(guided.headline('Quick setup check')).toBeVisible();
  await expect(guided.setupPrompt).toHaveText(`${prompt} ${line}`);
  await expect(guided.setupPrompt.getByText(prompt, { exact: true })).toHaveCSS('font-weight', BOLD);
  await expect(guided.cameraCue(prompt)).toBeVisible();
  expect(await hiddenFromScreenReaders(guided.cameraCue(prompt)), 'the camera cue is hidden from screen readers').toBe(true);
  await expect(guided.spoken(prompt)).toHaveCount(1);
  await expect(guided.spoken(prompt)).not.toHaveAttribute('aria-live', 'assertive');
  for (const other of SETUP_ORDER.filter((each) => each !== problem)) {
    await expect(guided.main.getByText(SETUP_PROMPTS[other].prompt, { exact: true })).toHaveCount(0);
  }
  expect(await guided.setupPrompt.innerText()).not.toMatch(CODED_TEXT);
  await expect(guided.main.getByText(/^Ref: /)).toHaveCount(0);
  await expect(guided.alert).toHaveCount(0);
}

function problemOf(text: string): SetupProblem | 'allGood' | null {
  if (startsWith(ALL_GOOD_PROMPT).test(text)) {
    return 'allGood';
  }
  return SETUP_ORDER.find((problem) => startsWith(SETUP_PROMPTS[problem].prompt).test(text)) ?? null;
}

async function promptChanges(page: Page): Promise<Array<{ at: number; problem: SetupProblem | 'allGood' }>> {
  const changes: Array<{ at: number; problem: SetupProblem | 'allGood' }> = [];
  for (const change of await recordedTextOf(page, 'setup-prompt')) {
    const problem = problemOf(change.text);
    if (problem !== null && changes.at(-1)?.problem !== problem) {
      changes.push({ at: change.at, problem });
    }
  }
  return changes;
}

async function timesSaid(page: Page, text: string): Promise<number> {
  return (await announcements(page)).filter((said) => said.text === text).length;
}

async function firstSaidAt(page: Page, pattern: RegExp): Promise<number> {
  const said = (await announcements(page)).find((each) => pattern.test(each.text));
  expect(said, `an announcement matching ${pattern.source}`).toBeDefined();
  return said?.at ?? Number.NaN;
}

async function outlineSpan(page: Page): Promise<number> {
  const guided = guidedPage(page);
  const boxes = await Promise.all((await guided.outlines.all()).map((outline) => boxOf(outline)));
  return Math.max(...boxes.map((box) => box.x + box.width)) - Math.min(...boxes.map((box) => box.x));
}

test.describe('setup check before the guided run', () => {
  test('lists the quick check first in the idle plan', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);

    await openGuidedRun(page);

    const plan = guided.main.getByRole('list').filter({ hasText: 'Warm-up, 60 s.' });
    await expect(plan.getByRole('listitem')).toHaveText([
      'Quick check, a few seconds. We nudge you until the camera gets a good look at you.',
      /^Warm-up, 60 s\./,
      /^Counted, 90 s\./,
      /^Result\./,
    ]);
    await expect(plan.getByText('Quick check, a few seconds.', { exact: true })).toHaveCSS('font-weight', BOLD);
    await expect(guided.setupCheck).toHaveCount(0);
  });

  test('runs the check after Start inside step 1, with Stop, four status rows and the run clock not started', async ({
    page,
  }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);

    await paceReplies(page, backend, SETTLE_MS);

    await expect(guided.phaseLine('Step 1 of 4, get comfy')).toBeVisible();
    await expectCurrentStep(page, 'Get comfy');
    await expect(guided.headline('Quick setup check')).toBeVisible();
    await expect(
      guided.main.getByText("Sit how you'll sit for the run. When all four say Good, the warm-up starts by itself.", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(guided.setupCheck.getByRole('listitem')).toHaveText([
      /^\s*Distance\s*(Good|Not yet)\s*$/,
      /^\s*Light\s*(Good|Not yet)\s*$/,
      /^\s*Stillness\s*(Good|Not yet)\s*$/,
      /^\s*Camera speed\s*(Good|Not yet)\s*$/,
    ]);
    await expect(guided.stop).toBeVisible();
    await expect(guided.start).toHaveCount(0);
    await expect(guided.warmUpTimer).toHaveCount(0);
    await expect(guided.countedTimer).toHaveCount(0);
    await expect(page).not.toHaveTitle(/^(Warm-up|Counting)\b/);
    expect(await timesSaid(page, 'Warm-up started. Stay in frame, no need to watch.')).toBe(0);
  });

  for (const problem of SETUP_ORDER) {
    const { why, setup, notYet } = ONE_PROBLEM[problem];
    const { prompt } = SETUP_PROMPTS[problem];

    test(`prompts "${prompt}" with its line, on the camera and once to screen readers, when ${why}`, async ({
      page,
    }) => {
      const opened = await openCheck(page, setup);

      await paceReplies(page, opened.backend, SETTLE_MS, opened.setup.stepMs);

      await expectOnlyPrompt(page, problem);
      await expectRows(page, notYet);
      expect(await timesSaid(page, prompt)).toBe(1);
      await expectCurrentStep(page, 'Get comfy');
    });
  }

  for (const { first, second, setup, notYet } of TWO_PROBLEMS) {
    test(`shows only "${SETUP_PROMPTS[first].prompt}" when ${ONE_PROBLEM[first].why} and ${ONE_PROBLEM[second].why}`, async ({
      page,
    }) => {
      const opened = await openCheck(page, setup);

      await paceReplies(page, opened.backend, SETTLE_MS, opened.setup.stepMs);

      await expectOnlyPrompt(page, first);
      await expectRows(page, notYet);
    });
  }

  test('keeps each prompt up at least 2 s while the problems keep flipping', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);
    await paceUntil(page, backend, guided.setupPrompt.getByText(SETUP_PROMPTS.far.prompt, { exact: true }), SETTLE_MS);

    for (let flip = 0; flip < 24; flip += 1) {
      if (flip % 2 === 0) {
        await showLight(page, 'behind');
        await paceReplies(page, backend, FRAME_SPACING_MS * 3);
        backend.setScene(faceScene());
      } else {
        backend.setScene(FAR);
        await paceReplies(page, backend, FRAME_SPACING_MS * 3);
        await showLight(page, 'even');
      }
      await paceReplies(page, backend, 300);
    }

    const changes = await promptChanges(page);
    const shown = new Set(changes.map((change) => change.problem));
    expect([...shown], 'prompts shown while flipping').toEqual(expect.arrayContaining(['far', 'behind']));
    const gaps = changes.slice(1).map((change, index) => change.at - changes[index].at);
    expect(
      gaps.filter((gap) => gap < PROMPT_HOLD_MS - FRAME_SPACING_MS),
      'prompt changes held under 2 s',
    ).toEqual([]);
  });

  test('starts the warm-up by itself after 3 s of all good, and the run clock starts only then', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: MOVING });
    const guided = guidedPage(page);
    await paceReplies(page, backend, SETTLE_MS);
    await expectOnlyPrompt(page, 'moving');

    backend.setScene(faceScene());
    const goodFrom = await pageNow(page);
    await paceUntil(page, backend, guided.headline('Looking good'), PROMPT_HOLD_MS + 1000);

    await expect(guided.setupPrompt).toHaveText(
      /^All good\. Hold that\. Warm-up starts in [1-3] s\. Stay just like that\.$/,
    );
    await expect(guided.setupPrompt.getByText(ALL_GOOD_PROMPT, { exact: true })).toHaveCSS('font-weight', BOLD);
    await expect(guided.cameraCue(ALL_GOOD_PROMPT)).toBeVisible();
    await expectRows(page, []);
    await expect(guided.anywayLine).toHaveCount(0);
    await expect(guided.startAnyway).toHaveCount(0);
    await expect(guided.warmUpTimer).toHaveCount(0);
    await expectCurrentStep(page, 'Get comfy');

    await paceUntil(page, backend, guided.warmUpTimer, ALL_GOOD_MS + PROMPT_HOLD_MS);

    const warmUpAt = await firstSaidAt(page, /^Warm-up started\b/);
    expect(warmUpAt - goodFrom, 'all good time before the warm-up').toBeGreaterThanOrEqual(ALL_GOOD_MS - FRAME_SPACING_MS);
    expect(warmUpAt - goodFrom, 'all good time before the warm-up').toBeLessThanOrEqual(ALL_GOOD_MS + PROMPT_HOLD_MS);
    expect(await timesSaid(page, 'All good. Warm-up starts in 3 seconds.')).toBe(1);
    expect(await timerSeconds(guided.warmUpTimer)).toBeGreaterThanOrEqual(59);
    await expectCurrentStep(page, 'Warm-up');
    await expect(guided.headline('Stay in frame. No need to watch.')).toBeVisible();
    await expect(guided.setupCheck).toHaveCount(0);
    await expect(guided.setupPrompt).toHaveCount(0);
    await expect(guided.cameraCue(ALL_GOOD_PROMPT)).toHaveCount(0);
  });

  test('starts the 3 s over when a check misses during the all good wait', async ({ page }) => {
    const { backend } = await openCheck(page);
    const guided = guidedPage(page);
    await paceUntil(page, backend, guided.headline('Looking good'), SETTLE_MS);
    await paceReplies(page, backend, ALL_GOOD_MS - 1000);
    await expect(guided.warmUpTimer).toHaveCount(0);

    backend.setScene(MOVING);
    await paceReplies(page, backend, FRAME_SPACING_MS * 6);
    await expect(guided.setupPrompt).toHaveText(startsWith(SETUP_PROMPTS.moving.prompt));
    await expect(guided.setupRow('Stillness').getByText('Not yet', { exact: true })).toBeVisible();
    backend.setScene(faceScene());
    const missEnded = await pageNow(page);

    await paceUntilPageTime(page, backend, missEnded + ALL_GOOD_MS - 2 * FRAME_SPACING_MS);
    await expect(guided.warmUpTimer).toHaveCount(0);
    await expectCurrentStep(page, 'Get comfy');

    await paceUntil(page, backend, guided.warmUpTimer, ALL_GOOD_MS + PROMPT_HOLD_MS);
    await expectCurrentStep(page, 'Warm-up');
  });

  test('shows Start anyway 15 s after the camera turns on, says so once and leaves focus where it was', async ({
    page,
  }) => {
    const { backend } = await openCheck(page, { light: 'behind' });
    const guided = guidedPage(page);
    const startedBy = await pageNow(page);
    await paceReplies(page, backend, 3000, LONG_STEP_MS);

    await expect(guided.anywayLine).toHaveText(/^Can't fix it right now\? Start anyway shows up in \d+ s\.$/);
    await expect(guided.startAnywayWait).toBeVisible();
    await expect(guided.startAnywayWait).toHaveAttribute('aria-valuemin', '0');
    await expect(guided.startAnywayWait).toHaveAttribute('aria-valuemax', '100');
    await expect(guided.startAnywayWait).toHaveAttribute('aria-valuetext', /^\d+ seconds to go$/);
    await expect(guided.startAnyway).toHaveCount(0);
    await guided.skinOutline.focus();

    await paceUntilPageTime(page, backend, startedBy + START_ANYWAY_MS - 1500, LONG_STEP_MS);
    await expect(guided.startAnyway).toHaveCount(0);

    await paceUntilPageTime(page, backend, startedBy + START_ANYWAY_MS + 500, LONG_STEP_MS);
    await expect(guided.startAnyway).toBeVisible();
    await expect(guided.anywayLine).toHaveText(
      "Can't fix it right now? You can start anyway. The reading may come out weaker.",
    );
    await expect(guided.startAnywayWait).toHaveCount(0);
    await expect(guided.skinOutline).toBeFocused();

    await paceReplies(page, backend, 3000, LONG_STEP_MS);
    expect(await timesSaid(page, START_ANYWAY_SAID)).toBe(1);
    expect((await announcements(page)).filter((said) => /shows up in/.test(said.text)), 'countdown spoken').toEqual([]);
    await expect(guided.setupPrompt).toHaveText(startsWith(SETUP_PROMPTS.behind.prompt));
    await expect(guided.skinOutline).toBeFocused();
    await expectCurrentStep(page, 'Get comfy');
  });

  test('goes straight into the warm-up from Start anyway, with the run clock starting then', async ({ page }) => {
    const { backend } = await openCheck(page, { light: 'behind' });
    const guided = guidedPage(page);
    await paceUntil(page, backend, guided.startAnyway, START_ANYWAY_MS + 2000, LONG_STEP_MS);

    await guided.startAnyway.click();
    await paceReplies(page, backend, 500);

    await expectCurrentStep(page, 'Warm-up');
    await expect(guided.warmUpTimer).toBeVisible();
    expect(await timerSeconds(guided.warmUpTimer)).toBeGreaterThanOrEqual(59);
    await expect(guided.setupCheck).toHaveCount(0);
    await expect(guided.startAnyway).toHaveCount(0);
    await expect(guided.cameraCue(SETUP_PROMPTS.behind.prompt)).toHaveCount(0);
    await expect(guided.stop).toBeVisible();
  });

  test('still starts the warm-up by itself when the problem is fixed after Start anyway shows', async ({ page }) => {
    const { backend } = await openCheck(page, { light: 'behind' });
    const guided = guidedPage(page);
    await paceUntil(page, backend, guided.startAnyway, START_ANYWAY_MS + 2000, LONG_STEP_MS);

    await showLight(page, 'even');
    await paceUntil(page, backend, guided.warmUpTimer, ALL_GOOD_MS + PROMPT_HOLD_MS + 1000);

    await expectCurrentStep(page, 'Warm-up');
    expect(await timerSeconds(guided.warmUpTimer)).toBeGreaterThanOrEqual(59);
  });

  test('draws the skin outline during the check, smaller when far away and none without a face', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);
    await paceReplies(page, backend, 1000);

    await expect(guided.headline('Quick setup check')).toBeVisible();
    await expect(guided.outlines).toHaveCount(3);
    const farSpan = await outlineSpan(page);

    backend.setScene(faceScene());
    await paceReplies(page, backend, 500);
    await expect(guided.outlines).toHaveCount(3);
    expect(farSpan).toBeLessThan((await outlineSpan(page)) * 0.75);

    backend.setScene(NO_FACE_SCENE);
    await paceReplies(page, backend, 1000);
    await expect(guided.outlines).toHaveCount(0);
    await expect(guided.warmUpTimer).toHaveCount(0);
    await expectCurrentStep(page, 'Get comfy');
  });

  test('does not bring the setup prompts back once the warm-up runs, and keeps the hold still hint', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);
    await paceReplies(page, backend, SETTLE_MS);
    await expectOnlyPrompt(page, 'far');
    backend.setScene(faceScene());
    await paceUntil(page, backend, guided.warmUpTimer, ALL_GOOD_MS + PROMPT_HOLD_MS + 1000);
    await expectCurrentStep(page, 'Warm-up');

    await showLight(page, 'behind');
    backend.setScene(faceWithSpan(FAR_SPAN_PX, { moving: true }));
    await paceReplies(page, backend, SETTLE_MS, SLOW_STEP_MS);

    for (const problem of SETUP_ORDER) {
      await expect(guided.main.getByText(SETUP_PROMPTS[problem].prompt, { exact: true })).toHaveCount(0);
    }
    await expect(guided.setupCheck).toHaveCount(0);
    await expect(guided.startAnyway).toHaveCount(0);
    await expect(guided.anywayLine).toHaveCount(0);
    await expect(guided.main.getByText("You're moving. Hold still.", { exact: true })).toBeVisible();
    await expectCurrentStep(page, 'Warm-up');
  });

  test('goes back to idle with the camera off when Stop is pressed during the check', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);
    await paceReplies(page, backend, 1000);
    await expect(guided.setupCheck).toBeVisible();

    await guided.stop.click();
    await page.clock.runFor(500);

    await expect(guided.start).toBeVisible();
    await expect(guided.startAgain).toHaveCount(0);
    await expect(guided.main.getByText(RUN_STOPPED_TEXT, { exact: true })).toHaveCount(0);
    await expect(guided.main.getByText("Camera's off. Press Start and your face shows up here.")).toBeVisible();
    await expect(guided.setupCheck).toHaveCount(0);
    await expectCurrentStep(page, 'Get comfy');
    await expect.poll(() => backend.openConnections().length).toBe(0);
  });

  test('reads distance, light, stillness and speed on the page, sending nothing new and storing nothing', async ({
    page,
  }) => {
    const requests: string[] = [];
    const { backend } = await openCheck(page, { light: 'behind' });
    const guided = guidedPage(page);
    page.on('request', (request) => requests.push(`${request.method()} ${request.url()}`));
    page.on('websocket', (socket) => requests.push(`websocket ${socket.url()}`));

    await paceReplies(page, backend, SETTLE_MS);

    await expect(guided.setupPrompt).toHaveText(startsWith(SETUP_PROMPTS.behind.prompt));
    expect(backend.textMessages).toEqual([]);
    expect(requests).toEqual([]);
    expect(backend.connections).toHaveLength(1);
    const stored = await page.evaluate(async () => ({
      local: localStorage.length,
      session: sessionStorage.length,
      databases: (await indexedDB.databases()).length,
      cookies: document.cookie,
    }));
    expect(stored).toEqual({ local: 0, session: 0, databases: 0, cookies: '' });
    expect(backend.frames.filter((frame) => frame.arrivedWhileAwaitingReply)).toEqual([]);
    expect(await frameRepliesSeen(page)).toBe(backend.frames.length);
  });

  test('stops reading frame pixels once the warm-up starts', async ({ page }) => {
    await countPixelReads(page);
    const { backend } = await openCheck(page);
    const guided = guidedPage(page);
    await paceUntil(page, backend, guided.warmUpTimer, SETTLE_MS + ALL_GOOD_MS);
    await paceReplies(page, backend, 200);
    const atWarmUp = await pixelReads(page);

    await paceReplies(page, backend, 2000);

    expect(atWarmUp, 'pixel reads during the check').toBeGreaterThan(0);
    expect(await pixelReads(page)).toBe(atWarmUp);
  });

  test('puts focus on Stop when Start anyway is pressed with the keyboard', async ({ page }) => {
    const { backend } = await openCheck(page, { light: 'behind' });
    const guided = guidedPage(page);
    await paceUntil(page, backend, guided.startAnyway, START_ANYWAY_MS + 2000, LONG_STEP_MS);
    await guided.startAnyway.focus();

    await page.keyboard.press('Enter');
    await paceReplies(page, backend, 300);

    await expectCurrentStep(page, 'Warm-up');
    await expect(guided.stop).toBeFocused();
  });

  test('puts focus on Stop when the check turns all good while Start anyway had focus', async ({ page }) => {
    const { backend } = await openCheck(page, { light: 'behind' });
    const guided = guidedPage(page);
    await paceUntil(page, backend, guided.startAnyway, START_ANYWAY_MS + 2000, LONG_STEP_MS);
    await guided.startAnyway.focus();

    await showLight(page, 'even');
    await paceUntil(page, backend, guided.headline('Looking good'), SETTLE_MS);

    await expect(guided.startAnyway).toHaveCount(0);
    await expect(guided.stop).toBeFocused();
  });

  test('ends as stopped with Start again when the link drops during the check, never blaming the camera', async ({
    page,
  }) => {
    const { backend } = await openCheck(page, { scene: MOVING });
    const guided = guidedPage(page);
    await paceReplies(page, backend, SETTLE_MS);
    await expectOnlyPrompt(page, 'moving');

    backend.dropOpenConnections({ code: 1006 });
    await page.clock.runFor(1000);

    await expect(guided.main.getByText('Ref: SOCKET_UNAVAILABLE', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect(guided.start).toHaveCount(0);
    await expect(guided.setupCheck).toHaveCount(0);
    expect(await timesSaid(page, SETUP_PROMPTS.slow.prompt)).toBe(0);
    expect((await promptChanges(page)).map((change) => change.problem)).not.toContain('slow');
  });

  test('ends as stopped with Start again when frame capture fails during the check', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);
    await paceReplies(page, backend, 1000);
    await expect(guided.setupCheck).toBeVisible();

    await failFrameEncoding(page, 'throws');
    await page.clock.runFor(1000);

    await expect(guided.main.getByText('Ref: FRAME_CAPTURE_FAILED', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect(guided.start).toHaveCount(0);
    await expect(guided.setupCheck).toHaveCount(0);
  });

  test('ends as stopped with Start again when the camera goes away during the check', async ({ page }) => {
    await spyOnCamera(page);
    const backend = await MockBackend.attach(page);
    backend.setScene(FAR);
    await page.clock.install();
    await startCheck(page, backend);
    await pauseClock(page);
    const guided = guidedPage(page);
    await paceReplies(page, backend, 1000);
    await expect(guided.setupCheck).toBeVisible();

    await endVideoTracks(page);
    await page.clock.runFor(1000);

    await expect(guided.main.getByText('Ref: CAMERA_LOST', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect(guided.start).toHaveCount(0);
    await expect(guided.setupCheck).toHaveCount(0);
  });
});

test.describe('setup check with reduced motion', () => {
  test.use({ reducedMotion: 'reduce' });

  test('keeps the start anyway bar, the rows and the prompts still when reduced motion is asked for', async ({ page }) => {
    const { backend } = await openCheck(page, { light: 'behind' });
    const guided = guidedPage(page);

    await paceReplies(page, backend, SETTLE_MS, LONG_STEP_MS);

    await expect(guided.startAnywayWait).toBeVisible();
    const parts = [
      guided.startAnywayWait,
      guided.setupCheck,
      guided.setupPrompt,
      guided.cameraCue(SETUP_PROMPTS.behind.prompt),
    ];
    for (const part of parts) {
      const moving = await part.evaluate((root) =>
        [root, ...root.querySelectorAll('*')]
          .filter((element) => {
            const style = getComputedStyle(element);
            const transitionMs = Math.max(...style.transitionDuration.split(',').map((each) => Number.parseFloat(each)));
            const animationMs = Math.max(...style.animationDuration.split(',').map((each) => Number.parseFloat(each)));
            const transitions = style.transitionProperty !== 'none' && transitionMs > 0;
            const animations = style.animationName !== 'none' && animationMs > 0;
            return transitions || animations;
          })
          .map((element) => element.tagName.toLowerCase()),
      );
      expect(moving, `moving parts in ${part.toString()}`).toEqual([]);
    }
  });
});
