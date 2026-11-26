import { expect, test, type Browser, type Locator, type Page } from '@playwright/test';
import {
  SETUP_BACKLIGHT_SHARE,
  SETUP_BRIGHTNESS_MAX,
  SETUP_BRIGHTNESS_MIN,
  SETUP_MIN_FACE_SPAN_PX,
  SETUP_MIN_FPS,
} from '../../../src/features/guided-capture/lib/setup-check';
import {
  advanceRun,
  advanceRunUntil,
  announcements,
  CALIBRATION_ROWS,
  calibrationBox,
  CLEAR_SHARE_ROW,
  FRAME_SPACING_MS,
  guidedPage,
  liveRegionsIn,
  LONG_STEP_MS,
  openGuidedRun,
  paceReplies,
  paceUntil,
  passSetupCheck,
  pauseClock,
  pushAndConfirm,
  recordAnnouncements,
  RUN_STOPPED_TEXT,
  setHrvAndConfirm,
  SETUP_PROMPTS,
  SLOW_STEP_MS,
  startsWith,
  type CalibrationRow,
  type SetupProblem,
  type SetupRow,
} from '../../support/guided-page';
import { installLitCamera, SHADES, showLight, type Light } from '../../support/lit-camera';
import {
  faceScene,
  faceSpanPx,
  faceWithSpan,
  hrv,
  MockBackend,
  NO_FACE_SCENE,
  type Hrv,
  type Scene,
} from '../../support/mock-backend';
import { boxOf, pageNow, setTabHidden } from '../../support/page-helpers';

const CALIBRATE = '/?calibrate';
const SETTLE_MS = 5000;
const SHORT_LOOK_MS = 2000;
const START_ANYWAY_MS = 15000;
const REDRAW_MS = 500;
const SHADE_SLACK = 12;
const MOST_FPS = 31;
const MOST_LIGHT_BEHIND = 90;
const FAR_SPAN_PX = SETUP_MIN_FACE_SPAN_PX / 2;
const NEAR_SPAN_PX = Math.round(faceSpanPx(faceScene()));
const FAR = faceWithSpan(FAR_SPAN_PX);

const SPAN: CalibrationRow = 'Face span (px)';
const BRIGHTNESS: CalibrationRow = 'Face brightness (0 to 255)';
const BACKLIGHT: CalibrationRow = 'Backlight (% near white)';
const FPS: CalibrationRow = 'Frames per second';
const FACE_ROWS: CalibrationRow[] = [SPAN, BRIGHTNESS, BACKLIGHT];

const LIMITS: Record<CalibrationRow, string> = {
  [SPAN]: `at least ${SETUP_MIN_FACE_SPAN_PX}`,
  [BRIGHTNESS]: `${SETUP_BRIGHTNESS_MIN} to ${SETUP_BRIGHTNESS_MAX}`,
  [BACKLIGHT]: `at most ${Math.round(SETUP_BACKLIGHT_SHARE * 100)}%`,
  [FPS]: `at least ${SETUP_MIN_FPS}`,
  [CLEAR_SHARE_ROW]: 'at least 50%',
};

const UNITS: Record<CalibrationRow, '' | '%'> = {
  [SPAN]: '',
  [BRIGHTNESS]: '',
  [BACKLIGHT]: '%',
  [FPS]: '',
  [CLEAR_SHARE_ROW]: '%',
};

const BOX_WORDS = /Calibration|Face span|Face brightness|Backlight|Frames per second|Waiting|Live, setup check|This run/;

const EARLIER = hrv({ rmssd_ms: 39.4, sdnn_ms: 45.2, minute_bpm: 68.4, minute_count: 66 });
const WITH_READING = hrv({ rmssd_ms: 41.2, sdnn_ms: 46.7, minute_bpm: 67.8, minute_count: 72 });
const FAINT = hrv({ minute_count: 9, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 18.4 });
const HALF_CLEAR = hrv({ minute_count: 30, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 50 });

type Setup = { scene: Scene; light: Light; stepMs: number };

const GOOD: Setup = { scene: faceScene(), light: 'even', stepMs: FRAME_SPACING_MS };

async function openCheck(
  page: Page,
  change: Partial<Setup> = {},
  address = CALIBRATE,
): Promise<{ backend: MockBackend; setup: Setup; startedBy: number }> {
  const setup = { ...GOOD, ...change };
  await installLitCamera(page, setup.light);
  await recordAnnouncements(page);
  const backend = await MockBackend.attach(page);
  backend.setScene(setup.scene);
  await page.clock.install();
  await openGuidedRun(page, address);
  const startedBy = await pageNow(page);
  await guidedPage(page).start.click();
  await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
  await pauseClock(page);
  return { backend, setup, startedBy };
}

async function finishRun(page: Page, backend: MockBackend, last: Hrv): Promise<void> {
  const guided = guidedPage(page);
  await page.clock.resume();
  await pushAndConfirm(page, backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
  await advanceRunUntil(page, backend, guided.countedTimer);
  await setHrvAndConfirm(page, backend, EARLIER);
  await advanceRun(page, backend, 60000);
  await setHrvAndConfirm(page, backend, last);
  await advanceRunUntil(page, backend, guided.startAgain);
}

async function shownWhole(cell: Locator, unit: '' | '%'): Promise<number> {
  const text = (await cell.innerText()).trim();
  const match = new RegExp(`^(\\d+)${unit}$`).exec(text);
  expect(match, `a whole number${unit === '' ? '' : ' with a % sign'}, shown as "${text}"`).not.toBeNull();
  return Number(match?.[1]);
}

async function rowTexts(page: Page): Promise<string[]> {
  const box = calibrationBox(page);
  const texts: string[] = [];
  for (const label of CALIBRATION_ROWS) {
    const value = (await box.value(label).innerText()).trim();
    const check = (await box.check(label).innerText()).trim();
    texts.push(`${label}: ${value} ${check}`);
  }
  return texts;
}

function allGoodRows() {
  return CALIBRATION_ROWS.map((label) => expect.stringMatching(new RegExp(`${startsWith(label).source}: \\d+%? Good$`)));
}

async function warmUpStartedAt(page: Page): Promise<number> {
  const said = (await announcements(page)).find((each) => /^Warm-up started\b/.test(each.text));
  expect(said, 'the warm-up start announcement').toBeDefined();
  return said?.at ?? Number.NaN;
}

async function secondsIn(line: Locator): Promise<number> {
  const match = /after (\d+) s\.$/.exec((await line.innerText()).trim());
  expect(match, 'the setup check line ends with whole seconds, like "after 9 s."').not.toBeNull();
  return Number(match?.[1]);
}

function expectAbout(seconds: number, fromMs: number, toMs: number): void {
  const took = (toMs - fromMs) / 1000;
  expect(seconds, `seconds shown for a check that took about ${took.toFixed(1)} s`).toBeGreaterThanOrEqual(Math.floor(took) - 1);
  expect(seconds, `seconds shown for a check that took about ${took.toFixed(1)} s`).toBeLessThanOrEqual(Math.ceil(took) + 1);
}

type ChangeWindow = Window & { spanChanges: Array<{ at: number; text: string }> };

async function watchSpanValue(page: Page): Promise<void> {
  await page.evaluate((label) => {
    const read = (): string => {
      const header = Array.from(document.querySelectorAll('main th, main [role="rowheader"]')).find(
        (cell) => cell.textContent?.trim() === label,
      );
      return header?.closest('tr, [role="row"]')?.querySelector('td, [role="cell"]')?.textContent?.trim() ?? '';
    };
    const changes = [{ at: performance.now(), text: read() }];
    Object.defineProperty(globalThis, 'spanChanges', { value: changes, configurable: true });
    new MutationObserver(() => {
      const text = read();
      if (changes.at(-1)?.text !== text) {
        changes.push({ at: performance.now(), text });
      }
    }).observe(document, { subtree: true, childList: true, characterData: true });
  }, SPAN);
}

function spanChanges(page: Page): Promise<Array<{ at: number; text: string }>> {
  return page.evaluate(() => [...(globalThis as unknown as ChangeWindow).spanChanges]);
}

function spillsOut(region: Locator): Promise<string[]> {
  return region.evaluate((root) => {
    const edge = root.getBoundingClientRect();
    const screenReaderOnly = (element: Element | null): boolean => {
      for (let node = element; node !== null && node !== root; node = node.parentElement) {
        const rect = node.getBoundingClientRect();
        const tiny = rect.width <= 1 || rect.height <= 1;
        const offScreen = rect.right <= 0 || rect.bottom <= 0 || rect.left >= innerWidth;
        if (tiny || offScreen) {
          return true;
        }
      }
      return false;
    };
    const spilled: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      const text = (node.textContent ?? '').trim();
      if (text === '' || screenReaderOnly(node.parentElement)) {
        continue;
      }
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const rect of Array.from(range.getClientRects())) {
        if (rect.left < edge.left - 0.5 || rect.right > edge.right + 0.5) {
          spilled.push(text);
        }
      }
    }
    if (root.scrollWidth > root.clientWidth + 1) {
      spilled.push(`the box scrolls sideways: ${root.scrollWidth} px of content in ${root.clientWidth} px`);
    }
    if (document.documentElement.scrollWidth > innerWidth) {
      spilled.push(`the page scrolls sideways: ${document.documentElement.scrollWidth} px in ${innerWidth} px`);
    }
    return spilled;
  });
}

async function expectStacked(page: Page, label: CalibrationRow): Promise<void> {
  const box = calibrationBox(page);
  const header = await boxOf(box.row(label).getByRole('rowheader'));
  const value = await boxOf(box.value(label));
  expect(value.y, `${label}: the value sits on a line under its label`).toBeGreaterThanOrEqual(header.y + header.height - 1);
}

test.describe('calibration readout flag', () => {
  test('keeps the box out of the page without the calibrate flag, through the check and the warm-up', async ({ page }) => {
    const { backend } = await openCheck(page, {}, '/');
    const guided = guidedPage(page);
    const box = calibrationBox(page);

    await paceUntil(page, backend, guided.headline('Looking good'), SETTLE_MS);

    await expect(guided.setupCheck).toBeVisible();
    await expect(box.region).toHaveCount(0);
    await expect(guided.main.getByText(BOX_WORDS)).toHaveCount(0);
    await expect(guided.main.getByText('?calibrate')).toHaveCount(0);
    await expect(guided.main.getByRole('table')).toHaveCount(0);

    await passSetupCheck(page, backend);

    await expect(guided.warmUpTimer).toBeVisible();
    await expect(box.region).toHaveCount(0);
    await expect(guided.main.getByRole('table')).toHaveCount(0);
  });

  for (const address of ['/?calibrated', '/?mode=calibrate', '/#calibrate']) {
    test(`keeps the box out of the page for ${address}, which carries no calibrate parameter`, async ({ page }) => {
      const { backend } = await openCheck(page, {}, address);
      const guided = guidedPage(page);

      await paceReplies(page, backend, SHORT_LOOK_MS);

      await expect(guided.setupCheck).toBeVisible();
      await expect(calibrationBox(page).region).toHaveCount(0);
      await expect(guided.main.getByText(BOX_WORDS)).toHaveCount(0);
    });
  }

  for (const address of ['/?calibrate', '/?calibrate=1', '/?calibrate=0', '/?calibrate=off', '/?theme=dark&calibrate']) {
    test(`shows the box during the check when the address is ${address}`, async ({ page }) => {
      const { backend } = await openCheck(page, {}, address);
      const box = calibrationBox(page);

      await paceReplies(page, backend, SHORT_LOOK_MS);

      await expect(box.region).toBeVisible();
      await expect(box.heading).toBeVisible();
      await expect(box.phase('Live, setup check')).toBeVisible();
      await expect(box.note).toBeVisible();
      await expect(box.rowHeaders).toHaveText([...CALIBRATION_ROWS]);
    });
  }

  test('keeps the box off the idle page with the flag and shows it once the camera runs', async ({ page }) => {
    await installLitCamera(page, 'even');
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await page.clock.install();

    await openGuidedRun(page, CALIBRATE);

    await expect(guided.start).toBeVisible();
    await expect(box.region).toHaveCount(0);

    await guided.start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);

    await expect(box.region).toBeVisible();
  });

  test('keeps the box and the clear share out of a no reading result without the calibrate flag', async ({ page }) => {
    const { backend } = await openCheck(page, {}, '/');
    const guided = guidedPage(page);
    await passSetupCheck(page, backend);

    await finishRun(page, backend, FAINT);

    await expect(guided.headline('Done, but no reading this time.')).toBeVisible();
    await expect(calibrationBox(page).region).toHaveCount(0);
    await expect(guided.main.getByText(/Clear share|Setup check: /)).toHaveCount(0);
  });
});

test.describe('calibration readout during the setup check', () => {
  test('lists the four measures in plain words with the limits the check uses, whole numbers and Good on a good setup', async ({
    page,
  }) => {
    const { backend } = await openCheck(page);
    const guided = guidedPage(page);
    const box = calibrationBox(page);

    await paceReplies(page, backend, SHORT_LOOK_MS);

    await expect(guided.warmUpTimer).toHaveCount(0);
    await expect(box.heading).toBeVisible();
    await expect(box.phase('Live, setup check')).toBeVisible();
    await expect(box.phase('This run')).toHaveCount(0);
    await expect(box.note).toBeVisible();
    await expect(box.columnHeaders).toHaveText(['Measure', 'Now', 'Limit', 'Check']);
    await expect(box.rowHeaders).toHaveText([...CALIBRATION_ROWS]);
    await expect(box.row(CLEAR_SHARE_ROW)).toHaveCount(0);
    await expect(box.runLine).toHaveCount(0);
    for (const label of CALIBRATION_ROWS) {
      await expect(box.limit(label), `${label} limit`).toHaveText(LIMITS[label]);
      await expect(box.check(label), `${label} check word`).toHaveText('Good');
      await expect(box.value(label), `${label} value`).toHaveText(UNITS[label] === '%' ? /^\d+%$/ : /^\d+$/);
    }
    await expect(box.value(SPAN)).toHaveText(String(NEAR_SPAN_PX));
    const brightness = await shownWhole(box.value(BRIGHTNESS), '');
    expect(brightness).toBeGreaterThanOrEqual(SHADES.even.face - SHADE_SLACK);
    expect(brightness).toBeLessThanOrEqual(SHADES.even.face + SHADE_SLACK);
    await expect(box.value(BACKLIGHT)).toHaveText('0%');
    const fps = await shownWhole(box.value(FPS), '');
    expect(fps).toBeGreaterThanOrEqual(SETUP_MIN_FPS);
    expect(fps).toBeLessThanOrEqual(MOST_FPS);
  });

  test('shows Waiting and Not yet on every row before the first sample comes back', async ({ page }) => {
    await installLitCamera(page, 'even');
    const backend = await MockBackend.attach(page);
    const box = calibrationBox(page);
    backend.holdReplies();
    await page.clock.install();
    await openGuidedRun(page, CALIBRATE);

    await guidedPage(page).start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(0);

    await expect(box.region).toBeVisible();
    for (const label of CALIBRATION_ROWS) {
      await expect(box.value(label), `${label} value`).toHaveText('Waiting');
      await expect(box.check(label), `${label} check word`).toHaveText('Not yet');
      await expect(box.limit(label), `${label} limit`).toHaveText(LIMITS[label]);
    }

    await pauseClock(page);
    backend.releaseReplies();
    await paceReplies(page, backend, SHORT_LOOK_MS);

    await expect(box.value(SPAN)).toHaveText(String(NEAR_SPAN_PX));
    await expect(box.check(SPAN)).toHaveText('Good');
  });

  test('shows Waiting and Not yet on the face rows while no face is found', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: NO_FACE_SCENE });
    const guided = guidedPage(page);
    const box = calibrationBox(page);

    await paceReplies(page, backend, SHORT_LOOK_MS);

    await expect(guided.setupPrompt).toHaveText(startsWith(SETUP_PROMPTS.noFace.prompt));
    for (const label of FACE_ROWS) {
      await expect(box.value(label), `${label} value`).toHaveText('Waiting');
      await expect(box.check(label), `${label} check word`).toHaveText('Not yet');
    }
    const fps = await shownWhole(box.value(FPS), '');
    expect(fps).toBeGreaterThanOrEqual(SETUP_MIN_FPS);
    await expect(box.check(FPS)).toHaveText('Good');
  });

  test('shows a face span just under the limit rounded up to the limit, with Not yet as the Distance row says', async ({
    page,
  }) => {
    const { backend } = await openCheck(page, { scene: faceWithSpan(SETUP_MIN_FACE_SPAN_PX - 0.4) });
    const guided = guidedPage(page);
    const box = calibrationBox(page);

    await paceReplies(page, backend, SHORT_LOOK_MS);

    await expect(box.value(SPAN)).toHaveText(String(SETUP_MIN_FACE_SPAN_PX));
    await expect(box.check(SPAN)).toHaveText('Not yet');
    await expect(guided.setupRow('Distance').getByText('Not yet', { exact: true })).toBeVisible();
  });

  test('shows Not measured on brightness and backlight when a face is found but its light cannot be read', async ({
    page,
  }) => {
    await page.addInitScript((reason) => {
      CanvasRenderingContext2D.prototype.getImageData = function refuseToRead(): never {
        throw new DOMException(reason, 'SecurityError');
      };
    }, 'The canvas refused to give its pixels in the test');
    const { backend } = await openCheck(page);
    const box = calibrationBox(page);

    await paceReplies(page, backend, SHORT_LOOK_MS);

    await expect(box.phase('Live, setup check')).toBeVisible();
    await expect(box.value(SPAN)).toHaveText(String(NEAR_SPAN_PX));
    await expect(box.check(SPAN)).toHaveText('Good');
    await expect(box.value(BRIGHTNESS)).toHaveText('Not measured');
    await expect(box.check(BRIGHTNESS)).toHaveText('Not yet');
    await expect(box.value(BACKLIGHT)).toHaveText('Not measured');
    await expect(box.check(BACKLIGHT)).toHaveText('Not yet');
  });

  const MISSES: Array<{
    why: string;
    setup: Partial<Setup>;
    misses: CalibrationRow;
    status: SetupRow;
    problem: SetupProblem;
    fits: string;
    holds: (value: number) => boolean;
  }> = [
    {
      why: 'the face is too far away',
      setup: { scene: FAR },
      misses: SPAN,
      status: 'Distance',
      problem: 'far',
      fits: `exactly ${FAR_SPAN_PX}`,
      holds: (value) => value === FAR_SPAN_PX,
    },
    {
      why: 'the room is dark',
      setup: { light: 'dark' },
      misses: BRIGHTNESS,
      status: 'Light',
      problem: 'dark',
      fits: `under ${SETUP_BRIGHTNESS_MIN}`,
      holds: (value) => value < SETUP_BRIGHTNESS_MIN,
    },
    {
      why: 'the face is washed out',
      setup: { light: 'bright' },
      misses: BRIGHTNESS,
      status: 'Light',
      problem: 'bright',
      fits: `from ${SETUP_BRIGHTNESS_MAX} to 255`,
      holds: (value) => value >= SETUP_BRIGHTNESS_MAX && value <= 255,
    },
    {
      why: 'there is light behind the face',
      setup: { light: 'behind' },
      misses: BACKLIGHT,
      status: 'Light',
      problem: 'behind',
      fits: `from ${MOST_LIGHT_BEHIND}% to 100%`,
      holds: (value) => value >= MOST_LIGHT_BEHIND && value <= 100,
    },
    {
      why: 'the camera is slow',
      setup: { stepMs: SLOW_STEP_MS },
      misses: FPS,
      status: 'Camera speed',
      problem: 'slow',
      fits: `from 1 to under ${SETUP_MIN_FPS}`,
      holds: (value) => value > 0 && value < SETUP_MIN_FPS,
    },
  ];

  for (const { why, setup, misses, status, problem, fits, holds } of MISSES) {
    test(`shows Not yet beside the measured ${misses} when ${why}, as the ${status} status row does`, async ({ page }) => {
      const opened = await openCheck(page, setup);
      const guided = guidedPage(page);
      const box = calibrationBox(page);

      await paceReplies(page, opened.backend, SETTLE_MS, opened.setup.stepMs);

      await expect(box.check(misses), `${misses} check word`).toHaveText('Not yet');
      const value = await shownWhole(box.value(misses), UNITS[misses]);
      expect(holds(value), `${misses} shows ${value}, expected ${fits}`).toBe(true);
      for (const label of CALIBRATION_ROWS.filter((each) => each !== misses)) {
        await expect(box.check(label), `${label} check word`).toHaveText('Good');
      }
      await expect(guided.setupRow(status).getByText('Not yet', { exact: true })).toBeVisible();
      await expect(guided.setupPrompt).toHaveText(startsWith(SETUP_PROMPTS[problem].prompt));
      await expect(guided.warmUpTimer).toHaveCount(0);
    });
  }

  test('updates the numbers live as the face moves in and the light changes', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const box = calibrationBox(page);
    await paceReplies(page, backend, SHORT_LOOK_MS);
    await expect(box.value(SPAN)).toHaveText(String(FAR_SPAN_PX));
    await expect(box.check(SPAN)).toHaveText('Not yet');

    backend.setScene(faceScene({ moving: true }));
    await paceReplies(page, backend, 2 * REDRAW_MS + FRAME_SPACING_MS);

    await expect(box.value(SPAN)).toHaveText(String(NEAR_SPAN_PX));
    await expect(box.check(SPAN)).toHaveText('Good');

    await showLight(page, 'dark');
    await paceReplies(page, backend, 2 * REDRAW_MS + FRAME_SPACING_MS);

    expect(await shownWhole(box.value(BRIGHTNESS), '')).toBeLessThan(SETUP_BRIGHTNESS_MIN);
    await expect(box.check(BRIGHTNESS)).toHaveText('Not yet');

    await showLight(page, 'behind');
    await paceReplies(page, backend, 2 * REDRAW_MS + FRAME_SPACING_MS);

    expect(await shownWhole(box.value(BACKLIGHT), '%')).toBeGreaterThanOrEqual(MOST_LIGHT_BEHIND);
    await expect(box.check(BACKLIGHT)).toHaveText('Not yet');
    await expect(box.phase('Live, setup check')).toBeVisible();
  });

  test('redraws the numbers at most twice a second even when every frame differs', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: faceWithSpan(FAR_SPAN_PX, { moving: true }) });
    const box = calibrationBox(page);
    await paceReplies(page, backend, SHORT_LOOK_MS);
    await expect(box.value(SPAN)).toHaveText(String(FAR_SPAN_PX));
    await watchSpanValue(page);
    const from = await pageNow(page);

    for (let frame = 0; frame < 60; frame += 1) {
      backend.setScene(frame % 2 === 0 ? faceScene({ moving: true }) : faceWithSpan(FAR_SPAN_PX, { moving: true }));
      await paceReplies(page, backend, FRAME_SPACING_MS);
    }

    const spent = (await pageNow(page)) - from;
    const redraws = (await spanChanges(page)).length - 1;
    expect(redraws, 'the face span changed on the page at least once').toBeGreaterThanOrEqual(1);
    expect(redraws, `face span redraws in ${Math.round(spent)} ms`).toBeLessThanOrEqual(Math.ceil(spent / REDRAW_MS) + 1);
  });

  test('announces nothing from the box and leaves focus where it was while the numbers change', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await paceReplies(page, backend, SHORT_LOOK_MS);
    await expect(box.region).toBeVisible();
    await guided.skinOutline.focus();

    backend.setScene(faceScene({ moving: true }));
    await paceReplies(page, backend, SHORT_LOOK_MS);
    await showLight(page, 'dark');
    await paceReplies(page, backend, SHORT_LOOK_MS);

    await expect(box.value(SPAN)).toHaveText(String(NEAR_SPAN_PX));
    expect(await liveRegionsIn(box.region), 'live regions inside the box').toEqual([]);
    const insideLive = await box.region.evaluate(
      (root) =>
        root.closest('[aria-live]:not([aria-live="off"]), [role="status"], [role="alert"], [role="log"], output') !== null,
    );
    expect(insideLive, 'the box sits inside a live region').toBe(false);
    const said = (await announcements(page)).filter((each) => BOX_WORDS.test(each.text));
    expect(said, 'announcements carrying the box text').toEqual([]);
    await expect(guided.skinOutline).toBeFocused();
  });

  test('sends nothing new over the socket or the network and stores nothing with the box on', async ({ page }) => {
    const requests: string[] = [];
    const { backend } = await openCheck(page);
    const guided = guidedPage(page);
    page.on('request', (request) => requests.push(`${request.method()} ${request.url()}`));
    page.on('websocket', (socket) => requests.push(`websocket ${socket.url()}`));

    await paceReplies(page, backend, SHORT_LOOK_MS);
    await expect(calibrationBox(page).region).toBeVisible();
    await passSetupCheck(page, backend);
    await advanceRun(page, backend, 5000, 1000);

    await expect(guided.warmUpTimer).toBeVisible();
    await expect(calibrationBox(page).phase('This run')).toBeVisible();
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
  });
});

test.describe('calibration readout after the setup check', () => {
  test('freezes the values when the check passes and keeps them under This run through warm-up and counting', async ({
    page,
  }) => {
    const { backend } = await openCheck(page);
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await paceUntil(page, backend, guided.headline('Looking good'), SETTLE_MS);
    await expect(box.phase('Live, setup check')).toBeVisible();

    await passSetupCheck(page, backend);
    await pauseClock(page);
    await paceReplies(page, backend, 2 * REDRAW_MS);

    await expect(guided.warmUpTimer).toBeVisible();
    await expect(box.phase('This run')).toBeVisible();
    await expect(box.phase('Live, setup check')).toHaveCount(0);
    await expect(box.columnHeaders).toHaveText(['Measure', 'Value', 'Limit', 'Check']);
    const frozen = await rowTexts(page);
    expect(frozen).toEqual(allGoodRows());

    backend.setScene(faceWithSpan(FAR_SPAN_PX, { moving: true }));
    await showLight(page, 'behind');
    await paceReplies(page, backend, SHORT_LOOK_MS, SLOW_STEP_MS);

    expect(await rowTexts(page), 'rows during the warm-up after the face and light changed').toEqual(frozen);
    await expect(box.phase('This run')).toBeVisible();

    backend.setScene(faceScene());
    await advanceRunUntil(page, backend, guided.countedTimer);
    await advanceRun(page, backend, 5000, 1000);

    await expect(guided.countedTimer).toBeVisible();
    await expect(box.region).toBeVisible();
    await expect(box.phase('This run')).toBeVisible();
    expect(await rowTexts(page), 'rows while counting').toEqual(frozen);
  });

  test('shows the four frozen rows and how long the check took, without a clear share, on a result with a reading', async ({
    page,
  }) => {
    const { backend, startedBy } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await paceReplies(page, backend, 6000);
    backend.setScene(faceScene());
    await passSetupCheck(page, backend);
    const passedAt = await warmUpStartedAt(page);
    await expect(box.phase('This run')).toBeVisible();
    const frozen = await rowTexts(page);

    await finishRun(page, backend, WITH_READING);

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expect(box.region).toBeVisible();
    await expect(box.phase('This run')).toBeVisible();
    await expect(box.note).toBeVisible();
    await expect(box.columnHeaders).toHaveText(['Measure', 'Value', 'Limit', 'Check']);
    await expect(box.rowHeaders).toHaveText([...CALIBRATION_ROWS]);
    await expect(box.row(CLEAR_SHARE_ROW)).toHaveCount(0);
    await expect(guided.main.getByText(/Clear share/)).toHaveCount(0);
    await expect(box.foot).toHaveCount(0);
    await expect(box.runLine).toHaveText(/^Setup check: passed after \d+ s\.$/);
    expectAbout(await secondsIn(box.runLine), startedBy, passedAt);
    expect(await rowTexts(page)).toEqual(frozen);
    expect(frozen).toEqual(allGoodRows());
    const heading = await boxOf(guided.headline('Done. Nice sitting.'));
    expect((await boxOf(box.region)).y).toBeGreaterThan(heading.y + heading.height);
  });

  test('adds the clear share against at least 50% with Not yet and the closing note, under the Ref line, on a no reading result', async ({
    page,
  }) => {
    const { backend } = await openCheck(page);
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await passSetupCheck(page, backend);

    await finishRun(page, backend, FAINT);

    await expect(guided.headline('Done, but no reading this time.')).toBeVisible();
    const ref = guided.main.getByText('Ref: READING_FLOOR_NOT_CLEARED', { exact: true });
    await expect(ref).toBeVisible();
    await expect(box.region).toBeVisible();
    await expect(box.phase('This run')).toBeVisible();
    await expect(box.runLine).toHaveText(/^Setup check: passed after \d+ s\.$/);
    await expect(box.rowHeaders).toHaveText([...CALIBRATION_ROWS, CLEAR_SHARE_ROW]);
    await expect(box.value(CLEAR_SHARE_ROW)).toHaveText('18%');
    await expect(box.limit(CLEAR_SHARE_ROW)).toHaveText(LIMITS[CLEAR_SHARE_ROW]);
    await expect(box.check(CLEAR_SHARE_ROW)).toHaveText('Not yet');
    await expect(box.foot).toBeVisible();
    expect(await rowTexts(page)).toEqual(allGoodRows());
    await expect(box.region.getByText(/Ref: /)).toHaveCount(0);
    await expect(guided.alert).toHaveCount(0);
    const refBox = await boxOf(ref);
    expect((await boxOf(box.region)).y, 'the box sits under the Ref line').toBeGreaterThanOrEqual(refBox.y + refBox.height - 1);
  });

  for (const { percent, shown, word } of [
    { percent: 50, shown: '50%', word: 'Good' },
    { percent: 49.6, shown: '50%', word: 'Good' },
    { percent: 49.4, shown: '49%', word: 'Not yet' },
  ] as const) {
    test(`judges a clear share of ${percent}% on the shown ${shown}, saying ${word}`, async ({ page }) => {
      const { backend } = await openCheck(page);
      const box = calibrationBox(page);
      await passSetupCheck(page, backend);

      await finishRun(page, backend, hrv({ ...HALF_CLEAR, clear_percent: percent }));

      await expect(guidedPage(page).headline('Done, but no reading this time.')).toBeVisible();
      await expect(box.value(CLEAR_SHARE_ROW)).toHaveText(shown);
      await expect(box.limit(CLEAR_SHARE_ROW)).toHaveText(LIMITS[CLEAR_SHARE_ROW]);
      await expect(box.check(CLEAR_SHARE_ROW)).toHaveText(word);
    });
  }

  for (const { name, last, code } of [
    { name: 'the signal was too weak', last: hrv({ no_reading: 'SIGNAL_TOO_WEAK' }), code: 'SIGNAL_TOO_WEAK' },
    { name: 'no reason came', last: hrv({ rmssd_ms: 33.6, sdnn_ms: 40.2, minute_count: 30 }), code: 'NO_READING' },
    {
      name: 'the clear share sent is out of range at 140%',
      last: hrv({ ...HALF_CLEAR, clear_percent: 140 }),
      code: 'READING_FLOOR_NOT_CLEARED',
    },
    {
      name: 'the clear share sent is out of range at -1%',
      last: hrv({ ...HALF_CLEAR, clear_percent: -1 }),
      code: 'READING_FLOOR_NOT_CLEARED',
    },
  ] as const) {
    test(`shows the clear share as Not measured and Not yet on a no reading result when ${name}`, async ({ page }) => {
      const { backend } = await openCheck(page);
      const guided = guidedPage(page);
      const box = calibrationBox(page);
      await passSetupCheck(page, backend);

      await finishRun(page, backend, last);

      await expect(guided.headline('Done, but no reading this time.')).toBeVisible();
      await expect(guided.main.getByText(`Ref: ${code}`, { exact: true })).toBeVisible();
      await expect(box.rowHeaders).toHaveText([...CALIBRATION_ROWS, CLEAR_SHARE_ROW]);
      await expect(box.value(CLEAR_SHARE_ROW)).toHaveText('Not measured');
      await expect(box.limit(CLEAR_SHARE_ROW)).toHaveText(LIMITS[CLEAR_SHARE_ROW]);
      await expect(box.check(CLEAR_SHARE_ROW)).toHaveText('Not yet');
      await expect(box.foot).toBeVisible();
    });
  }

  test('says the check was started anyway after how long, with Not yet on the rows that never passed', async ({ page }) => {
    const { backend, startedBy } = await openCheck(page, { light: 'behind' });
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await paceUntil(page, backend, guided.startAnyway, START_ANYWAY_MS + 2000, LONG_STEP_MS);
    const pressedAt = await pageNow(page);

    await guided.startAnyway.click();
    await paceReplies(page, backend, REDRAW_MS);
    await expect(guided.warmUpTimer).toBeVisible();
    await finishRun(page, backend, WITH_READING);

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expect(box.runLine).toHaveText(/^Setup check: started anyway after \d+ s\.$/);
    expectAbout(await secondsIn(box.runLine), startedBy, pressedAt);
    await expect(box.check(BACKLIGHT)).toHaveText('Not yet');
    expect(await shownWhole(box.value(BACKLIGHT), '%')).toBeGreaterThanOrEqual(MOST_LIGHT_BEHIND);
    await expect(box.check(FPS)).toHaveText('Not yet');
    await expect(box.check(SPAN)).toHaveText('Good');
    await expect(box.check(BRIGHTNESS)).toHaveText('Good');
    await expect(box.row(CLEAR_SHARE_ROW)).toHaveCount(0);
  });

  test('freezes Not measured and Not yet on the face rows after Start anyway when no face was ever seen', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: NO_FACE_SCENE });
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await paceUntil(page, backend, guided.startAnyway, START_ANYWAY_MS + 2000);

    await guided.startAnyway.click();
    await paceReplies(page, backend, 2 * REDRAW_MS);

    await expect(guided.warmUpTimer).toBeVisible();
    await expect(box.phase('This run')).toBeVisible();
    for (const label of FACE_ROWS) {
      await expect(box.value(label), `${label} value`).toHaveText('Not measured');
      await expect(box.check(label), `${label} check word`).toHaveText('Not yet');
    }
    expect(await shownWhole(box.value(FPS), '')).toBeGreaterThanOrEqual(SETUP_MIN_FPS);
  });
});

test.describe('calibration readout leaving with the camera', () => {
  test('takes the box away when Stop is pressed during the check', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await paceReplies(page, backend, SHORT_LOOK_MS);
    await expect(box.region).toBeVisible();

    await guided.stop.click();
    await page.clock.runFor(REDRAW_MS);

    await expect(guided.start).toBeVisible();
    await expect(box.region).toHaveCount(0);
  });

  test('takes the box away when Stop ends the run during the warm-up', async ({ page }) => {
    const { backend } = await openCheck(page);
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await passSetupCheck(page, backend);
    await advanceRun(page, backend, 5000, 1000);
    await expect(box.phase('This run')).toBeVisible();

    await guided.stop.click();

    await expect(guided.main.getByText(RUN_STOPPED_TEXT, { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect(box.region).toHaveCount(0);
  });

  test('takes the box away when the link to the pulse reader drops during the check', async ({ page }) => {
    const { backend } = await openCheck(page, { scene: FAR });
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await paceReplies(page, backend, SHORT_LOOK_MS);
    await expect(box.region).toBeVisible();

    backend.dropOpenConnections({ code: 1006 });
    await page.clock.runFor(1000);

    await expect(guided.main.getByText('Ref: SOCKET_UNAVAILABLE', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect(box.region).toHaveCount(0);
  });

  test('takes the box away when the page is hidden during the warm-up', async ({ page }) => {
    const { backend } = await openCheck(page);
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await passSetupCheck(page, backend);
    await advanceRun(page, backend, 5000, 1000);
    await expect(box.phase('This run')).toBeVisible();

    await setTabHidden(page, true);
    await expect.poll(() => backend.openConnections().length).toBe(0);
    await setTabHidden(page, false);

    await expect(guided.main.getByText('Ref: PAGE_HIDDEN', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect(box.region).toHaveCount(0);
  });
});

test.describe('calibration readout layout at desktop width', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('sits last in the side panel under the pulse trace with each value beside its label', async ({ page }) => {
    const { backend } = await openCheck(page);
    const guided = guidedPage(page);
    const box = calibrationBox(page);

    await paceReplies(page, backend, SHORT_LOOK_MS);

    await expect(box.region).toBeVisible();
    const region = await boxOf(box.region);
    const trace = await boxOf(guided.pulseTrace);
    const video = await boxOf(guided.video);
    expect(region.y, 'the box sits under the pulse trace').toBeGreaterThanOrEqual(trace.y + trace.height - 1);
    expect(region.x, 'the box sits in the side panel').toBeGreaterThanOrEqual(video.x + video.width - 1);
    for (const label of CALIBRATION_ROWS) {
      const header = await boxOf(box.row(label).getByRole('rowheader'));
      const value = await boxOf(box.value(label));
      expect(value.x, `${label}: the value sits beside its label`).toBeGreaterThanOrEqual(header.x + header.width - 1);
    }
    expect(await spillsOut(box.region)).toEqual([]);
  });
});

test.describe('calibration readout layout at phone width', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('stacks each row under its label with nothing running out of the box during the check', async ({ page }) => {
    const { backend } = await openCheck(page, { light: 'behind' });
    const box = calibrationBox(page);

    await paceReplies(page, backend, SHORT_LOOK_MS);

    await expect(box.region).toBeVisible();
    expect((await boxOf(box.region)).width, 'the box is under 360 px wide at phone width').toBeLessThan(360);
    for (const label of CALIBRATION_ROWS) {
      await expectStacked(page, label);
      await expect(box.row(label)).toContainText(LIMITS[label]);
    }
    await expect(box.columnHeaders).toHaveText(['Measure', 'Now', 'Limit', 'Check']);
    expect(await spillsOut(box.region)).toEqual([]);
  });

  test('keeps the no reading result box with the clear share and its note inside its edges', async ({ page }) => {
    const { backend } = await openCheck(page);
    const box = calibrationBox(page);
    await passSetupCheck(page, backend);

    await finishRun(page, backend, FAINT);

    await expect(box.row(CLEAR_SHARE_ROW)).toBeVisible();
    await expect(box.foot).toBeVisible();
    await expect(box.runLine).toBeVisible();
    for (const label of [...CALIBRATION_ROWS, CLEAR_SHARE_ROW] as const) {
      await expectStacked(page, label);
    }
    expect(await spillsOut(box.region)).toEqual([]);
  });
});

async function stopButtonDuringCheck(
  browser: Browser,
  viewport: { width: number; height: number },
  flagged: boolean,
): Promise<Awaited<ReturnType<typeof boxOf>>> {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const { backend } = await openCheck(page, { scene: faceScene({ moving: true }) }, flagged ? CALIBRATE : '/');
  await paceReplies(page, backend, SHORT_LOOK_MS);
  const guided = guidedPage(page);
  await expect(guided.stop).toBeVisible();
  await expect(calibrationBox(page).region, `the box ${flagged ? 'with' : 'without'} the flag`).toHaveCount(flagged ? 1 : 0);
  const box = await boxOf(guided.stop);
  await context.close();
  return box;
}

for (const viewport of [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'phone', size: { width: 390, height: 844 } },
] as const) {
  test(`keeps the main button where it is with and without the calibrate flag during the check at ${viewport.name} width`, async ({
    browser,
  }) => {
    const without = await stopButtonDuringCheck(browser, viewport.size, false);
    const flagged = await stopButtonDuringCheck(browser, viewport.size, true);

    for (const side of ['x', 'y', 'width', 'height'] as const) {
      expect(Math.abs(flagged[side] - without[side]), `Stop button ${side} with the flag`).toBeLessThanOrEqual(1);
    }
  });
}
