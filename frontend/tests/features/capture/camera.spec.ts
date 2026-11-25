import { expect, test, type Page } from '@playwright/test';
import { expectQuietRef, guidedPage, openGuidedRun, startRun } from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import {
  cameraTrackIds,
  cameraTrackStates,
  CODED_ALERT_TEXT,
  endVideoTracks,
  failPreviewAttach,
  recordTrackStops,
  recordUnhandledRejections,
  refuseCamera,
  removeCameraApi,
  spyOnCamera,
  stoppedTrackIds,
  unhandledRejections,
} from '../../support/page-helpers';

const START_FAILED = {
  message: "Starting the camera hit something this page didn't expect, so it stopped cleanly.",
  action: 'Press Start again. If it keeps happening, reload the page.',
};

async function expectCameraOff(page: Page): Promise<void> {
  await expect.poll(() => cameraTrackStates(page)).not.toHaveLength(0);
  await expect.poll(async () => (await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
}

test.describe('camera', () => {
  test('stops every camera track when the page is left mid-run', async ({ page }) => {
    await spyOnCamera(page);
    await recordTrackStops(page);
    const backend = await MockBackend.attach(page);
    await startRun(page, backend);
    const tracks = await cameraTrackIds(page);
    expect(tracks).not.toHaveLength(0);
    expect(await stoppedTrackIds(page)).toEqual([]);

    await page.goto('/?left');

    const stopped = await stoppedTrackIds(page);
    expect(tracks.filter((id) => !stopped.includes(id))).toEqual([]);
  });

  test('shows the plain CAMERA_LOST text, offers Start again and closes the socket when the camera goes away', async ({
    page,
  }) => {
    await spyOnCamera(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    const [streaming] = backend.openConnections();

    await endVideoTracks(page);

    await expectQuietRef(
      guided.main,
      'The camera dropped out mid-run. It was unplugged, switched off or grabbed by another app.',
      'CAMERA_LOST',
    );
    await expect(guided.main.getByText('Check the camera is plugged in and free, then press Start again.')).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect.poll(() => streaming.closedBy).toBe('page');
    expect(backend.openConnections()).toHaveLength(0);
    await expectCameraOff(page);
  });

  test('shows the plain CAMERA_IN_USE text when the camera fails with AbortError', async ({ page }) => {
    await refuseCamera(page, 'AbortError');
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await guided.start.click();

    await expectQuietRef(guided.main, "The camera is there, but another app is sitting on it and won't share.", 'CAMERA_IN_USE');
    await expect(guided.main.getByText('Ref: CAMERA_NOT_FOUND', { exact: true })).toHaveCount(0);
    await expect(guided.start).toBeVisible();
  });

  test('shows the plain CAMERA_NOT_FOUND text when the camera fails with OverconstrainedError', async ({ page }) => {
    await refuseCamera(page, 'OverconstrainedError');
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await guided.start.click();

    await expectQuietRef(guided.main, 'No camera turned up, or none that can do what this page needs.', 'CAMERA_NOT_FOUND');
    await expect(guided.main.getByText(/another app/i)).toHaveCount(0);
    await expect(guided.main.getByText('Ref: CAMERA_IN_USE', { exact: true })).toHaveCount(0);
    await expect(guided.start).toBeVisible();
  });

  for (const errorName of ['TypeError', 'InvalidStateError'] as const) {
    test(`shows START_FAILED, not CAMERA_NOT_FOUND, when the camera fails with an unexpected ${errorName}`, async ({
      page,
    }) => {
      await refuseCamera(page, errorName);
      await MockBackend.attach(page);
      const guided = guidedPage(page);
      await openGuidedRun(page);

      await guided.start.click();

      await expectQuietRef(guided.main, START_FAILED.message, 'START_FAILED');
      await expect(guided.main.getByText(START_FAILED.action)).toBeVisible();
      await expect(guided.main.getByText('Ref: CAMERA_NOT_FOUND', { exact: true })).toHaveCount(0);
      await expect(guided.main.getByText(/\bplug/i)).toHaveCount(0);
      await expect(guided.start).toBeVisible();
      await expect(guided.stop).toHaveCount(0);
    });
  }

  test('shows the plain CAMERA_UNSUPPORTED text when navigator getUserMedia is missing', async ({ page }) => {
    await removeCameraApi(page, 'getUserMedia');
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await guided.start.click();

    await expectQuietRef(
      guided.main,
      "This browser won't share the camera here. Browsers only do that on a secure or local address.",
      'CAMERA_UNSUPPORTED',
    );
    await expect(guided.main.getByText('Ref: CAMERA_NOT_FOUND', { exact: true })).toHaveCount(0);
    await expect(guided.start).toBeVisible();
  });

  test('ends in START_FAILED with Start back, not stuck starting, when the preview refuses the camera stream', async ({
    page,
  }) => {
    await spyOnCamera(page);
    await recordUnhandledRejections(page);
    await failPreviewAttach(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await guided.start.click();

    await expectQuietRef(guided.main, START_FAILED.message, 'START_FAILED');
    const codes = (await guided.main.innerText()).match(new RegExp(CODED_ALERT_TEXT.source, 'g')) ?? [];
    expect(codes).toEqual(['START_FAILED']);
    await expect(guided.start).toBeVisible();
    await expect(guided.stop).toHaveCount(0);
    await expectCameraOff(page);
    expect(backend.openConnections()).toHaveLength(0);
    expect(await unhandledRejections(page)).toEqual([]);
  });
});
