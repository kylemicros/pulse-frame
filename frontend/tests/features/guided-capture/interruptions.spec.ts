import { expect, test, type Page } from '@playwright/test';
import {
  advanceRun,
  advanceRunUntil,
  expectCurrentStep,
  expectQuietRef,
  guidedPage,
  openGuidedRun,
  pushAndConfirm,
  RUN_MS,
  RUN_STOPPED_TEXT,
  startRun,
} from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import {
  cameraTrackStates,
  CODED_ALERT_TEXT,
  refuseCamera,
  removeCameraApi,
  setTabHidden,
  spyOnCamera,
  watchedText,
  watchText,
} from '../../support/page-helpers';
import { drawnTexts, expectNoResultTiles } from '../../support/result-states';

const ANOTHER_CONNECTION_OPEN = { code: 1013, reason: 'ANOTHER_CONNECTION_OPEN' };
const DROPPED = { code: 1006 };
const BUSY_MESSAGE = 'The app is busy in another tab or window, so the run stopped.';
const BUSY_ACTION = 'Close the other one, then press Start again.';
const UNREACHABLE_MESSAGE = "Can't reach the pulse reader, so the run stopped.";
const UNREACHABLE_ACTION = 'Check pulse frame is running on this computer, then press Start again.';
const CAMERA_OFF_STOPPED = "Camera's off. The run stopped.";

async function expectCameraAndSocketClosed(page: Page, backend: MockBackend): Promise<void> {
  await expect.poll(async () => (await cameraTrackStates(page)).length).toBeGreaterThan(0);
  await expect.poll(async () => (await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
  await expect.poll(() => backend.openConnections().length).toBe(0);
}

async function expectNoResultLater(page: Page, backend: MockBackend): Promise<void> {
  const guided = guidedPage(page);
  backend.acceptEveryConnection();
  await advanceRun(page, backend, RUN_MS);
  await expect(guided.headline('Done. Nice sitting.')).toHaveCount(0);
  await expect(guided.headline('Done, but no reading this time.')).toHaveCount(0);
  await expect(guided.main.getByText('Average over the last counted minute.', { exact: true })).toHaveCount(0);
  await expect(guided.countedTimer).toHaveCount(0);
  await expect(guided.startAgain).toBeVisible();
  expect(backend.openConnections()).toEqual([]);
}

test.describe('guided run interruptions', () => {
  test('shows plain camera denied guidance with a quiet Ref: CAMERA_DENIED last line', async ({ page }) => {
    await refuseCamera(page, 'NotAllowedError');
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await guided.start.click();

    await expect(guided.alert).toBeVisible();
    await expect(guided.alert).toContainText('The browser said no to the camera, so there is nothing to read.');
    await expect(guided.alert).toContainText(
      "Allow the camera for this page in the browser's site settings, then press Start again.",
    );
    const lines = (await guided.alert.innerText()).split('\n').map((line) => line.trim()).filter(Boolean);
    expect(lines.at(-1)).toBe('Ref: CAMERA_DENIED');
    expect(lines.slice(0, -1).join(' ')).not.toMatch(CODED_ALERT_TEXT);
    await expect(guided.main.getByText("Camera's off. The browser said no.")).toBeVisible();
    expect(await drawnTexts(guided.cameraBox), 'words drawn on the camera box').toEqual(["Camera's off. The browser said no."]);
    await expectCurrentStep(page, 'Get comfy');
    await expect(guided.start).toBeVisible();
    await expectNoResultTiles(page);
  });

  const cameraCases = [
    {
      code: 'CAMERA_IN_USE',
      refuse: (page: Page) => refuseCamera(page, 'NotReadableError'),
      message: "The camera is there, but another app is sitting on it and won't share.",
      action: 'Quit the other app that has the camera (a video call, Photo Booth), then press Start again.',
      cameraLine: "Camera's off. Another app has it.",
    },
    {
      code: 'CAMERA_NOT_FOUND',
      refuse: (page: Page) => refuseCamera(page, 'NotFoundError'),
      message: 'No camera turned up, or none that can do what this page needs.',
      action: 'Plug a camera in, give it a second to wake up, then press Start again.',
      cameraLine: "Camera's off. No camera found.",
    },
    {
      code: 'CAMERA_UNSUPPORTED',
      refuse: (page: Page) => removeCameraApi(page, 'mediaDevices'),
      message: "This browser won't share the camera here. Browsers only do that on a secure or local address.",
      action: 'Open pulse frame at its local address in an up to date browser, then press Start.',
      cameraLine: "Camera's off. This browser won't share it here.",
    },
  ] as const;

  for (const camera of cameraCases) {
    test(`shows the plain ${camera.code} text, a quiet Ref and only its camera line on the camera box`, async ({ page }) => {
      await camera.refuse(page);
      await MockBackend.attach(page);
      const guided = guidedPage(page);
      await openGuidedRun(page);
      expect(await drawnTexts(guided.cameraBox), 'words drawn on the camera box').toEqual([]);

      await guided.start.click();

      await expectQuietRef(guided.main, camera.message, camera.code);
      await expect(guided.main.getByText(camera.action)).toBeVisible();
      await expect(guided.main.getByText(camera.cameraLine, { exact: true })).toBeVisible();
      expect(await drawnTexts(guided.cameraBox), 'words drawn on the camera box').toEqual([camera.cameraLine]);
      await expectCurrentStep(page, 'Get comfy');
    });
  }

  test('stops the run when the app is busy elsewhere mid-run, with a quiet Ref: SOCKET_BUSY and no result', async ({
    page,
  }) => {
    await spyOnCamera(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);
    await pushAndConfirm(page, backend, { bpm: 70.2, quality_db: 9.3, state: 'ok' });

    backend.refuseEveryConnection(ANOTHER_CONNECTION_OPEN);
    backend.dropOpenConnections(ANOTHER_CONNECTION_OPEN);

    await expectQuietRef(guided.main, BUSY_MESSAGE, 'SOCKET_BUSY');
    await expect(guided.main.getByText(BUSY_ACTION)).toBeVisible();
    await expect(guided.main.getByText(CAMERA_OFF_STOPPED, { exact: true })).toBeVisible();
    expect(await drawnTexts(guided.cameraBox), 'words drawn on the camera box').toEqual([CAMERA_OFF_STOPPED]);
    await expectCameraAndSocketClosed(page, backend);
    await expectNoResultLater(page, backend);
  });

  test('stops the run when the pulse reader drops mid-run, with a quiet Ref: SOCKET_UNAVAILABLE and no result', async ({
    page,
  }) => {
    await spyOnCamera(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRunUntil(page, backend, guided.countedTimer);
    await pushAndConfirm(page, backend, { bpm: 70.2, quality_db: 9.3, state: 'ok' });

    backend.refuseEveryConnection(DROPPED);
    backend.dropOpenConnections(DROPPED);

    await expectQuietRef(guided.main, UNREACHABLE_MESSAGE, 'SOCKET_UNAVAILABLE');
    await expect(guided.main.getByText(UNREACHABLE_ACTION)).toBeVisible();
    await expect(guided.main).not.toContainText(/backend|127\.0\.0\.1|uv run|python/i);
    await expect(guided.main.getByText(CAMERA_OFF_STOPPED, { exact: true })).toBeVisible();
    expect(await drawnTexts(guided.cameraBox), 'words drawn on the camera box').toEqual([CAMERA_OFF_STOPPED]);
    await expectCameraAndSocketClosed(page, backend);
    await expectNoResultLater(page, backend);
  });

  test('stops the run when the browser tab is hidden and explains it with a quiet Ref: PAGE_HIDDEN last', async ({
    page,
  }) => {
    await spyOnCamera(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRun(page, backend, 10000);

    await setTabHidden(page, true);

    await expectCameraAndSocketClosed(page, backend);
    await page.clock.fastForward(30000);
    await setTabHidden(page, false);

    await expect(guided.main).toContainText('Keep this tab in front for the whole run, then press Start again.');
    await expectQuietRef(guided.main, 'The page was hidden, so the run stopped.', 'PAGE_HIDDEN');
    await expect(guided.main.getByText(CAMERA_OFF_STOPPED, { exact: true })).toBeVisible();
    expect(await drawnTexts(guided.cameraBox), 'words drawn on the camera box').toEqual([CAMERA_OFF_STOPPED]);
    await expect(guided.startAgain).toBeVisible();
    await expect(guided.stop).toHaveCount(0);
    await expect(guided.countedTimer).toHaveCount(0);
    await expect(guided.warmUpTimer).toHaveCount(0);
    await expect(page).not.toHaveTitle(/^(Warm-up|Counting),/);
  });

  test('ends the run, turns the camera off and says so plainly when Stop is pressed', async ({ page }) => {
    await spyOnCamera(page);
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await advanceRun(page, backend, 10000);
    await watchText(guided.milestones, 'milestones');

    await guided.stop.click();

    await expectCameraAndSocketClosed(page, backend);
    await expect(guided.main.getByText(RUN_STOPPED_TEXT, { exact: true })).toBeVisible();
    await expect(guided.milestones).toHaveText(RUN_STOPPED_TEXT);
    await expect(guided.milestones).toHaveRole('status');
    const spoken = (await watchedText(page, 'milestones')).map((change) => change.text.trim());
    expect(spoken.filter((text) => text === RUN_STOPPED_TEXT)).toHaveLength(1);
    await expect(guided.main.getByText("Camera's off. Run stopped.", { exact: true })).toBeVisible();
    await expect(guided.main).not.toContainText(/Ref: /);
    await expect(guided.startAgain).toBeVisible();
    await expect(guided.warmUpTimer).toHaveCount(0);
    await expect(page).not.toHaveTitle(/^(Warm-up|Counting),/);
  });
});
