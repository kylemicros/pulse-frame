import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { CHECK_SETTLE_MS, CHECK_SETTLED_MS, EARLIER, FAR_FACE } from './support/app-shell';
import {
  advanceRun,
  advanceRunUntil,
  CALIBRATION_ROWS,
  calibrationBox,
  drawnPrompt,
  FRAME_SPACING_MS,
  guidedPage,
  paceReplies,
  paceUntil,
  passSetupCheck,
  pauseClock,
  pushAndConfirm,
  RUN_STOPPED_TEXT,
  SETUP_PROMPTS,
  setHrvAndConfirm,
  SLOW_STEP_MS,
  termLines,
  type SetupProblem,
} from './support/guided-page';
import { installLitCamera, type Light } from './support/lit-camera';
import {
  faceScene,
  hrv,
  MockBackend,
  NO_FACE_SCENE,
  STREAM_URL,
  type Hrv,
  type Scene,
} from './support/mock-backend';
import { headerLogo } from './support/brand';
import {
  chooseTheme,
  openSettings,
  PAGE_BACKGROUND,
  pageBackground,
  setSetting,
  settingsPanel,
  tabTo,
} from './support/settings';
import { startBuiltPreview, type BuiltPreview } from './support/built-preview';
import {
  endVideoTracks,
  longestPathCommands,
  refuseCamera,
  setTabHidden,
  spyOnCamera,
  videoIsPlaying,
} from './support/page-helpers';
import { expectNoResultTiles, idleHeadline, resultHero } from './support/result-states';

const START_ANYWAY_BUDGET_MS = 17000;
const CALIBRATE_SEARCH = '?calibrate';

type CheckState = { light: Light | null; scene: Scene; stepMs: number };

const VIEWPORTS = [
  { name: 'desktop', size: { width: 1280, height: 800 }, panelScrolls: true },
  { name: 'desktop-wide', size: { width: 1920, height: 1080 }, panelScrolls: true },
  { name: 'tablet', size: { width: 820, height: 1180 }, panelScrolls: false },
  { name: 'phone', size: { width: 390, height: 844 }, panelScrolls: false },
] as const;

const OK_READING = { bpm: 72.4, quality_db: 6.3, state: 'ok' } as const;
const SHOWN_BPM = /^(72\.4|72)$/;

const FAKE_DEVICE_LABELS: Record<MediaDeviceKind, RegExp> = {
  videoinput: /^fake_device_\d+$/,
  audioinput: /^Fake (Default )?Audio Input( \d+)?$/,
  audiooutput: /^Fake (Default )?Audio Output( \d+)?$/,
};

type ListedDevice = { kind: MediaDeviceKind; label: string };

type Session = { page: Page; backend: MockBackend; networkSocketUrls: string[] };

type PageSocketsWindow = Window & { socketRecords: Array<{ url: string }> };

function listDevices(page: Page): Promise<ListedDevice[]> {
  return page.evaluate(async () =>
    (await navigator.mediaDevices.enumerateDevices()).map((device) => ({ kind: device.kind, label: device.label })),
  );
}

async function expectOnlyFakeDevices(page: Page): Promise<void> {
  const devices = await listDevices(page);
  const cameraCount = devices.filter((device) => device.kind === 'videoinput').length;
  const notFakeKinds = devices
    .filter((device) => !FAKE_DEVICE_LABELS[device.kind].test(device.label))
    .map((device) => device.kind);

  expect(cameraCount, 'Chromium lists no fake camera').toBeGreaterThan(0);
  expect(notFakeKinds, 'kinds of the listed devices that are not Chromium fake devices').toEqual([]);
}

async function attachMockOnly(page: Page): Promise<Session> {
  const networkSocketUrls: string[] = [];
  page.on('websocket', (socket) => networkSocketUrls.push(socket.url()));
  const backend = await MockBackend.attach(page);
  return { page, backend, networkSocketUrls };
}

function pageSocketUrls(page: Page): Promise<string[]> {
  return page.evaluate(() => (globalThis as unknown as PageSocketsWindow).socketRecords.map((record) => record.url));
}

async function expectOnlyMockedSockets({ page, backend, networkSocketUrls }: Session): Promise<void> {
  const opened = await pageSocketUrls(page);

  expect(opened.filter((url) => url !== STREAM_URL), 'sockets opened to a URL the mock does not serve').toEqual([]);
  await expect
    .poll(() => backend.connections.filter((connection) => connection.accepted).length, {
      message: 'sockets the page opened that the mock did not accept',
    })
    .toBe(opened.length);
  expect(networkSocketUrls, 'sockets that reached the network instead of the mock').toEqual([]);
}

async function capture(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await page.mouse.move(0, 0);
  await shootPage(page, testInfo, name);
}

async function shootPage(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await page.screenshot({
    path: testInfo.outputPath(`${name}.png`),
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
  });
}

function dropFocus(page: Page): Promise<void> {
  return page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
}

async function startCheckOnly(page: Page, session: Session): Promise<void> {
  await guidedPage(page).start.click();
  await expect.poll(() => session.backend.frames.length).toBeGreaterThan(1);
}

async function startGuidedRun(page: Page, session: Session): Promise<void> {
  await startCheckOnly(page, session);
  await passSetupCheck(page, session.backend);
}

async function runToEnd(page: Page, session: Session, last: Hrv): Promise<void> {
  const guided = guidedPage(page);
  await startGuidedRun(page, session);
  await pushAndConfirm(page, session.backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
  await advanceRunUntil(page, session.backend, guided.countedTimer);
  await setHrvAndConfirm(page, session.backend, EARLIER);
  await advanceRun(page, session.backend, 60000);
  await setHrvAndConfirm(page, session.backend, last);
  await advanceRunUntil(page, session.backend, guided.startAgain);
}

async function guidedLinkLost(page: Page, session: Session, close: { code: number; reason?: string }): Promise<void> {
  await startGuidedRun(page, session);
  await advanceRun(page, session.backend, 10000, 2500);
  await pushAndConfirm(page, session.backend, OK_READING);
  await expectOnlyMockedSockets(session);
  session.backend.refuseEveryConnection(close);
  session.backend.dropOpenConnections(close);
}

async function scrollPanelToEnd(page: Page, regionName: 'Setup check details' | 'Counting details'): Promise<void> {
  const region = page.getByRole('main').getByRole('region', { name: regionName, exact: true });
  await expect(region).toBeVisible();
  await region.focus();
  await page.keyboard.press('End');
  await expect
    .poll(() => region.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop))
    .toBeLessThanOrEqual(1);
  await expect(calibrationBox(page).region).toBeInViewport();
}

test.describe('guided page screenshots', () => {
  test.describe.configure({ mode: 'default' });

  let site: BuiltPreview | null = null;

  test.beforeAll(async () => {
    site = await startBuiltPreview();
  });

  test.afterAll(async () => {
    await site?.close();
  });

  async function openBuiltPage(page: Page, search = ''): Promise<void> {
    const url = site?.url ?? '';
    expect(url).not.toBe('');
    await page.goto(`${url}${search}`);
    await expectOnlyFakeDevices(page);
  }

  async function openBuiltGuidedRun(page: Page, light: Light | null = null, search = ''): Promise<Session> {
    if (light !== null) {
      await installLitCamera(page, light);
    }
    const session = await attachMockOnly(page);
    await page.clock.install();
    await openBuiltPage(page, search);
    const guided = guidedPage(page);
    await expect(guided.stepList).toBeVisible();
    await expect(page.getByRole('tablist')).toHaveCount(0);
    return session;
  }

  async function headerWithLogo(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const logo = headerLogo(page);

    await expect(logo.wordmark).toBeVisible();
    await expect(logo.mark).toBeVisible();
    expect(session.backend.connections).toEqual([]);
    await expectOnlyMockedSockets(session);
    await page.mouse.move(0, 0);
    await logo.banner.screenshot({
      path: testInfo.outputPath(`${name}.png`),
      animations: 'disabled',
      caret: 'hide',
    });
  }

  async function guidedIdle(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await expect(guided.start).toBeVisible();
    await expect(guided.lock).toBeVisible();
    await expect(guided.outlines).toHaveCount(0);
    await expect(idleHeadline(page)).toBeVisible();
    await expectNoResultTiles(page);
    expect(session.backend.connections).toEqual([]);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedWarmUp(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);

    await advanceRun(page, session.backend, 12000, 2500);

    await expect(guided.warmUpTimer).toBeVisible();
    await expect(guided.settleBar).toBeVisible();
    await expect.poll(() => videoIsPlaying(guided.video)).toBe(true);
    await expect(guided.outlines).toHaveCount(3);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedOutlineOff(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await advanceRun(page, session.backend, 12000, 2500);
    await expect(guided.outlines).toHaveCount(3);

    await setSetting(page, 'Skin outline', false);
    await dropFocus(page);
    await advanceRun(page, session.backend, 1000, 250);

    await expect(guided.outlines).toHaveCount(0);
    await expect.poll(() => videoIsPlaying(guided.video)).toBe(true);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedCounting(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await advanceRunUntil(page, session.backend, guided.countedTimer);
    await pushAndConfirm(page, session.backend, { bpm: 67.2, quality_db: 9.1, state: 'ok' });

    session.backend.setScene(faceScene({ moving: true }));
    await advanceRun(page, session.backend, 3000, 1000);

    await expect(guided.main.getByText("You're moving. Hold still.", { exact: true })).toBeVisible();
    await expect(guided.liveReadings.getByText(/^67(\.2)?$/)).toBeVisible();
    await expect(guided.outlines).toHaveCount(3);
    await expect.poll(() => longestPathCommands(guided.pulseTrace)).toBeGreaterThan(10);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedCountingVariation(
    page: Page,
    testInfo: TestInfo,
    name: string,
    fields: Hrv,
    shown: { beatToBeat: string; overall: string },
  ): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await advanceRunUntil(page, session.backend, guided.countedTimer);
    await pushAndConfirm(page, session.backend, { bpm: 66.2, quality_db: 6.1, state: 'ok' });

    await setHrvAndConfirm(page, session.backend, fields);
    await advanceRun(page, session.backend, 2000, 500);

    await expect.poll(() => termLines(guided.liveReadings, 'Beat to beat variation')).toEqual([
      expect.stringMatching(new RegExp(`^${shown.beatToBeat}`)),
      'Counted part so far',
    ]);
    await expect.poll(() => termLines(guided.liveReadings, 'Overall rhythm variation')).toEqual([
      expect.stringMatching(new RegExp(`^${shown.overall}`)),
      'Newest counted minute',
    ]);
    await expect(guided.variationLine).toBeVisible();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  function guidedOneVariation(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return guidedCountingVariation(page, testInfo, name, hrv({ rmssd_ms: 38.2, minute_count: 20 }), {
      beatToBeat: '38',
      overall: 'Not enough beats yet',
    });
  }

  function guidedBothVariations(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return guidedCountingVariation(
      page,
      testInfo,
      name,
      hrv({ rmssd_ms: 39.4, sdnn_ms: 45.2, minute_bpm: 66.4, minute_count: 66 }),
      { beatToBeat: '39', overall: '45' },
    );
  }

  async function guidedDone(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await runToEnd(page, session, hrv({ rmssd_ms: 41.2, sdnn_ms: 46.7, minute_bpm: 67.8, minute_count: 72 }));

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expect(resultHero(page).hero).toBeVisible();
    await expect(resultHero(page).number(68)).toBeVisible();
    await expect(guided.main.getByRole('definition').filter({ hasText: 'BPM' })).toHaveText(/^\s*68\s*BPM\s*$/);
    await expect(resultHero(page).variationLine).toBeVisible();
    await expect(guided.video).toBeHidden();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedDoneRange(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await runToEnd(
      page,
      session,
      hrv({ rmssd_ms: 41.2, sdnn_ms: 46.7, minute_bpm: 67.8, minute_count: 72, bpm_low: 66.4, bpm_high: 69.3 }),
    );

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expect
      .poll(() => termLines(guided.main, 'Heart rate'))
      .toEqual([expect.stringMatching(/^68 ?BPM$/), 'Average over the last counted minute. Likely 66 to 70.']);
    await expect(resultHero(page).hero).toBeVisible();
    await expect(resultHero(page).variationLine).toBeVisible();
    await expect(guided.video).toBeHidden();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedNoReadingWith(
    page: Page,
    testInfo: TestInfo,
    name: string,
    last: Hrv | null,
    code: string,
  ): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    if (last === null) {
      await startGuidedRun(page, session);
      await advanceRunUntil(page, session.backend, guided.startAgain);
    } else {
      await runToEnd(page, session, last);
    }

    await expect(guided.headline('Done, but no reading this time.')).toBeVisible();
    await expect(guided.main.getByText(`Ref: ${code}`, { exact: true })).toBeVisible();
    await expect(resultHero(page).noReading).toBeVisible();
    await expect(resultHero(page).hero.getByText('Not enough beats this time', { exact: true })).toHaveCount(2);
    await expect(guided.video).toBeHidden();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  function guidedNoReading(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return guidedNoReadingWith(page, testInfo, name, null, 'NO_READING');
  }

  function guidedNoReadingFaint(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return guidedNoReadingWith(
      page,
      testInfo,
      name,
      hrv({ minute_count: 9, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 18.4 }),
      'READING_FLOOR_NOT_CLEARED',
    );
  }

  function guidedNoReadingFace(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return guidedNoReadingWith(
      page,
      testInfo,
      name,
      hrv({ minute_count: 14, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'face_left_view' }),
      'READING_FLOOR_NOT_CLEARED',
    );
  }

  function guidedNoReadingWeak(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return guidedNoReadingWith(page, testInfo, name, hrv({ no_reading: 'SIGNAL_TOO_WEAK' }), 'SIGNAL_TOO_WEAK');
  }

  async function guidedCameraDenied(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    await refuseCamera(page, 'NotAllowedError');
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await guided.start.click();

    await expect(guided.alert).toContainText('Ref: CAMERA_DENIED');
    await expectNoResultTiles(page);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedCameraLost(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    await spyOnCamera(page);
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await advanceRun(page, session.backend, 10000, 2500);
    await expect(guided.warmUpTimer).toBeVisible();
    await expectOnlyMockedSockets(session);

    await endVideoTracks(page);
    await page.clock.runFor(1000);

    await expect(guided.alert).toContainText('Ref: CAMERA_LOST');
    await expect(guided.main.getByText("Camera's off. It dropped out.", { exact: true })).toBeVisible();
    await expectNoResultTiles(page);
    await expect(guided.startAgain).toBeVisible();
    await capture(page, testInfo, name);
  }

  async function guidedLastGood(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await pushAndConfirm(page, session.backend, OK_READING);
    await expect(guided.liveReadings.getByText(SHOWN_BPM)).toBeVisible();

    await pushAndConfirm(page, session.backend, { bpm: null, quality_db: 1.2, state: 'low_quality' });
    await advanceRun(page, session.backend, 2000, 500);

    await expect(guided.liveReadings.getByText(SHOWN_BPM)).toBeVisible();
    await expect(guided.liveReadings.getByText('Last good', { exact: true })).toBeVisible();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedBusy(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await guidedLinkLost(page, session, { code: 1013, reason: 'ANOTHER_CONNECTION_OPEN' });

    await expect(guided.main.getByText('Ref: SOCKET_BUSY', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect.poll(() => session.backend.openConnections().length).toBe(0);
    await capture(page, testInfo, name);
  }

  async function guidedUnreachable(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await guidedLinkLost(page, session, { code: 1006 });

    await expect(guided.main.getByText('Ref: SOCKET_UNAVAILABLE', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect.poll(() => session.backend.openConnections().length).toBe(0);
    await capture(page, testInfo, name);
  }

  async function guidedHiddenTab(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await advanceRun(page, session.backend, 10000, 2500);
    await expectOnlyMockedSockets(session);

    await setTabHidden(page, true);
    await expect.poll(() => session.backend.openConnections().length).toBe(0);
    await setTabHidden(page, false);

    await expect(guided.main.getByText('Ref: PAGE_HIDDEN', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await capture(page, testInfo, name);
  }

  async function guidedStopped(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await advanceRun(page, session.backend, 10000, 2500);
    await expectOnlyMockedSockets(session);

    await guided.stop.click();

    await expect(guided.main.getByText(RUN_STOPPED_TEXT, { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect.poll(() => session.backend.openConnections().length).toBe(0);
    await capture(page, testInfo, name);
  }

  async function openBuiltCheck(page: Page, check: CheckState, search = ''): Promise<Session> {
    const session = await openBuiltGuidedRun(page, check.light, search);
    session.backend.setScene(check.scene);
    await startCheckOnly(page, session);
    await pauseClock(page);
    return session;
  }

  function guidedCheckPrompt(problem: SetupProblem, change: Partial<CheckState>) {
    const check: CheckState = { light: null, scene: faceScene(), stepMs: FRAME_SPACING_MS, ...change };
    return async (page: Page, testInfo: TestInfo, name: string): Promise<void> => {
      const session = await openBuiltCheck(page, check);
      const guided = guidedPage(page);
      const prompt = drawnPrompt(page, SETUP_PROMPTS[problem].prompt);

      await paceUntil(page, session.backend, prompt, CHECK_SETTLE_MS, check.stepMs);
      await paceReplies(page, session.backend, CHECK_SETTLED_MS, check.stepMs);

      await expect(guided.headline('Quick setup check')).toBeVisible();
      await expect(prompt).toBeVisible();
      await expect(guided.setupCheck).toBeVisible();
      await expect(guided.startAnywayWait).toBeVisible();
      await expectOnlyMockedSockets(session);
      await capture(page, testInfo, name);
    };
  }

  async function guidedCheckStartAnyway(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltCheck(page, { light: 'behind', scene: faceScene(), stepMs: FRAME_SPACING_MS });
    const guided = guidedPage(page);

    await paceUntil(page, session.backend, guided.startAnyway, START_ANYWAY_BUDGET_MS);
    await paceReplies(page, session.backend, CHECK_SETTLED_MS);

    await expect(guided.startAnyway).toBeVisible();
    await expect(drawnPrompt(page, SETUP_PROMPTS.behind.prompt)).toBeVisible();
    await expect(guided.setupRow('Light').getByText('Not yet', { exact: true })).toBeVisible();
    for (const row of ['Distance', 'Stillness', 'Camera speed'] as const) {
      await expect(guided.setupRow(row).getByText('Good', { exact: true })).toBeVisible();
    }
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedCheckAllGood(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltCheck(page, { light: 'even', scene: faceScene(), stepMs: FRAME_SPACING_MS });
    const guided = guidedPage(page);

    await paceUntil(page, session.backend, guided.headline('Looking good'), CHECK_SETTLE_MS);

    await expect(guided.setupCheck).toBeVisible();
    await expect(guided.warmUpTimer).toHaveCount(0);
    await expect(guided.outlines).toHaveCount(3);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function calibrateCheck(page: Page, testInfo: TestInfo, name: string, light: Light): Promise<void> {
    const session = await openBuiltCheck(page, { light, scene: faceScene(), stepMs: FRAME_SPACING_MS }, CALIBRATE_SEARCH);
    const box = calibrationBox(page);

    await paceReplies(page, session.backend, 2 * CHECK_SETTLED_MS);

    await expect(guidedPage(page).warmUpTimer).toHaveCount(0);
    await expect(box.region).toBeVisible();
    await expect(box.phase('Live, setup check')).toBeVisible();
    await expect(box.rowHeaders).toHaveText([...CALIBRATION_ROWS]);
    await expect(box.value('Face span (px)')).toHaveText(/^\d+$/);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  function calibrateCheckGood(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return calibrateCheck(page, testInfo, name, 'even');
  }

  function calibrateCheckBehind(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return calibrateCheck(page, testInfo, name, 'behind');
  }

  async function calibrateWarmUp(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page, null, CALIBRATE_SEARCH);
    const guided = guidedPage(page);
    const box = calibrationBox(page);
    await startGuidedRun(page, session);

    await advanceRun(page, session.backend, 12000, 2500);

    await expect(guided.warmUpTimer).toBeVisible();
    await expect(box.phase('This run')).toBeVisible();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function reachCalibrateCounting(page: Page): Promise<Session> {
    const session = await openBuiltGuidedRun(page, null, CALIBRATE_SEARCH);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await pushAndConfirm(page, session.backend, { bpm: 67.2, quality_db: 9.1, state: 'ok' });
    await advanceRunUntil(page, session.backend, guided.countedTimer);
    await setHrvAndConfirm(page, session.backend, EARLIER);
    await advanceRun(page, session.backend, 3000, 1000);

    await expect(guided.countedTimer).toBeVisible();
    await expect(calibrationBox(page).phase('This run')).toBeVisible();
    await expectOnlyMockedSockets(session);
    return session;
  }

  async function calibrateCounting(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    await reachCalibrateCounting(page);
    await capture(page, testInfo, name);
  }

  async function calibrateCheckScrolled(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltCheck(
      page,
      { light: 'even', scene: faceScene(), stepMs: FRAME_SPACING_MS },
      CALIBRATE_SEARCH,
    );
    await paceReplies(page, session.backend, 2 * CHECK_SETTLED_MS);
    await expect(calibrationBox(page).phase('Live, setup check')).toBeVisible();

    await scrollPanelToEnd(page, 'Setup check details');

    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function calibrateCountingScrolled(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    await reachCalibrateCounting(page);

    await scrollPanelToEnd(page, 'Counting details');

    await capture(page, testInfo, name);
  }

  async function calibrateDone(page: Page, testInfo: TestInfo, name: string, last: Hrv): Promise<void> {
    const session = await openBuiltGuidedRun(page, null, CALIBRATE_SEARCH);
    const box = calibrationBox(page);

    await runToEnd(page, session, last);

    await expect(guidedPage(page).startAgain).toBeVisible();
    await expect(box.phase('This run')).toBeVisible();
    await expect(box.runLine).toHaveText(/^Setup check: passed after \d+ s\.$/);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  function calibrateDoneReading(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return calibrateDone(page, testInfo, name, hrv({ rmssd_ms: 41.2, sdnn_ms: 46.7, minute_bpm: 67.8, minute_count: 72 }));
  }

  function calibrateDoneNoReading(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    return calibrateDone(
      page,
      testInfo,
      name,
      hrv({ minute_count: 9, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 18.4 }),
    );
  }

  async function settingsOpenIdle(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const settings = settingsPanel(page);

    await openSettings(page);

    await expect(settings.skinOutline).toBeChecked();
    await expect(settings.privacy).toBeVisible();
    expect(session.backend.connections).toEqual([]);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function settingsOpenCounting(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    await reachCalibrateCounting(page);
    const settings = settingsPanel(page);

    await openSettings(page);

    await expect(settings.calibrationNumbers).toBeChecked();
    await expect(settings.privacy).toBeVisible();
    await capture(page, testInfo, name);
  }

  async function lockWordsShown(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await tabTo(page, guided.lock);

    await expect(guided.lockWords).toBeVisible();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function startHovered(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await expect(guided.start).toBeVisible();
    await guided.start.hover();
    await expectOnlyMockedSockets(session);
    await shootPage(page, testInfo, name);
  }

  async function themeDarkChosen(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);

    await chooseTheme(page, 'Dark');
    await dropFocus(page);

    await expect.poll(() => pageBackground(page)).toBe(PAGE_BACKGROUND.dark);
    expect(session.backend.connections).toEqual([]);
    await capture(page, testInfo, name);
  }

  const GUIDED_STATES = [
    { state: 'header-logo', title: 'the page header with the logo', shoot: headerWithLogo },
    { state: 'settings-open', title: 'Settings open on the idle page', shoot: settingsOpenIdle },
    { state: 'settings-open-counting', title: 'Settings open mid-run while counting', shoot: settingsOpenCounting },
    { state: 'lock-words', title: 'the camera lock showing its words on keyboard focus', shoot: lockWordsShown },
    { state: 'theme-dark-chosen', title: 'the page with Dark chosen in Settings', shoot: themeDarkChosen },
    { state: 'start-hover', title: 'the main button on hover', shoot: startHovered },
    { state: 'idle', title: 'the guided run idle page', shoot: guidedIdle },
    {
      state: 'check-no-face',
      title: 'the setup check with no face found',
      shoot: guidedCheckPrompt('noFace', { scene: NO_FACE_SCENE }),
    },
    { state: 'check-far', title: 'the setup check with the face too far away', shoot: guidedCheckPrompt('far', { scene: FAR_FACE }) },
    {
      state: 'check-behind',
      title: 'the setup check with light behind the face',
      shoot: guidedCheckPrompt('behind', { light: 'behind' }),
    },
    { state: 'check-dark', title: 'the setup check in a dark room', shoot: guidedCheckPrompt('dark', { light: 'dark' }) },
    {
      state: 'check-bright',
      title: 'the setup check with the face washed out',
      shoot: guidedCheckPrompt('bright', { light: 'bright' }),
    },
    {
      state: 'check-slow',
      title: 'the setup check with a slow camera',
      shoot: guidedCheckPrompt('slow', { stepMs: SLOW_STEP_MS }),
    },
    {
      state: 'check-moving',
      title: 'the setup check asking to hold still',
      shoot: guidedCheckPrompt('moving', { scene: faceScene({ moving: true }) }),
    },
    { state: 'check-start-anyway', title: 'the setup check with start anyway ready', shoot: guidedCheckStartAnyway },
    { state: 'check-all-good', title: 'the setup check all good before the warm-up', shoot: guidedCheckAllGood },
    { state: 'warm-up', title: 'the guided run warm-up with the skin outline on', shoot: guidedWarmUp },
    { state: 'outline-off', title: 'the guided run warm-up with the skin outline off', shoot: guidedOutlineOff },
    { state: 'counting', title: 'the guided run counting with the hold still hint', shoot: guidedCounting },
    { state: 'one-variation', title: 'the guided run counting with one variation value in', shoot: guidedOneVariation },
    { state: 'both-variations', title: 'the guided run counting with both variation values in', shoot: guidedBothVariations },
    { state: 'done', title: 'the guided run result', shoot: guidedDone },
    { state: 'done-range', title: 'the guided run result with a likely range', shoot: guidedDoneRange },
    { state: 'no-reading', title: 'the guided run with no reading and no reason', shoot: guidedNoReading },
    { state: 'no-reading-faint', title: 'the guided run with no reading from a faint pulse', shoot: guidedNoReadingFaint },
    { state: 'no-reading-face', title: 'the guided run with no reading as the face left view', shoot: guidedNoReadingFace },
    { state: 'no-reading-weak', title: 'the guided run with no reading from a weak signal', shoot: guidedNoReadingWeak },
    { state: 'camera-denied', title: 'the guided run camera denied guidance', shoot: guidedCameraDenied },
    { state: 'camera-lost', title: 'the guided run stopped as the camera dropped out in the warm-up', shoot: guidedCameraLost },
    { state: 'last-good', title: 'the guided run holding the last good heart rate', shoot: guidedLastGood },
    { state: 'busy', title: 'the guided run stopped because the app is busy elsewhere', shoot: guidedBusy },
    { state: 'unreachable', title: 'the guided run stopped because the pulse reader is unreachable', shoot: guidedUnreachable },
    { state: 'hidden-tab', title: 'the guided run stopped because the tab was hidden', shoot: guidedHiddenTab },
    { state: 'run-stopped', title: 'the guided run stopped with Stop', shoot: guidedStopped },
    { state: 'calibrate-check', title: 'the calibration readout live during a good setup check', shoot: calibrateCheckGood },
    {
      state: 'calibrate-check-behind',
      title: 'the calibration readout live with light behind the face',
      shoot: calibrateCheckBehind,
    },
    { state: 'calibrate-warm-up', title: 'the calibration readout frozen during the warm-up', shoot: calibrateWarmUp },
    { state: 'calibrate-counting', title: 'the calibration readout while counting', shoot: calibrateCounting },
    { state: 'calibrate-done', title: 'the calibration readout on a result with a reading', shoot: calibrateDoneReading },
    {
      state: 'calibrate-no-reading',
      title: 'the calibration readout with the clear share on a no reading result',
      shoot: calibrateDoneNoReading,
    },
  ] as const;

  const PANEL_SCROLL_STATES = [
    {
      state: 'calibrate-check-scrolled',
      title: 'the side panel scrolled to its end during the setup check',
      shoot: calibrateCheckScrolled,
    },
    {
      state: 'calibrate-counting-scrolled',
      title: 'the side panel scrolled to its end while counting',
      shoot: calibrateCountingScrolled,
    },
  ] as const;

  for (const viewport of VIEWPORTS) {
    const states = viewport.panelScrolls ? [...GUIDED_STATES, ...PANEL_SCROLL_STATES] : GUIDED_STATES;

    test.describe(`${viewport.name} guided run screenshots`, () => {
      test.use({ viewport: viewport.size });

      for (const { state, title, shoot } of states) {
        test(`screenshots ${title} at ${viewport.name} width`, async ({ page }, testInfo) => {
          await shoot(page, testInfo, `${viewport.name}-guided-${state}`);
        });
      }
    });

    test.describe(`${viewport.name} guided run dark theme screenshots`, () => {
      test.use({ viewport: viewport.size, colorScheme: 'dark' });

      for (const { state, title, shoot } of states) {
        test(`screenshots ${title} in the dark theme at ${viewport.name} width`, async ({ page }, testInfo) => {
          await shoot(page, testInfo, `${viewport.name}-dark-guided-${state}`);
        });
      }
    });
  }
});
