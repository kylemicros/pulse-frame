import { expect, test } from '@playwright/test';
import { jpegSize } from '../../support/jpeg';
import { MockBackend } from '../../support/mock-backend';
import {
  cameraTrackStates,
  failFrameEncoding,
  monitorPage,
  ownTextLength,
  pageNow,
  recordUnhandledRejections,
  setTabHidden,
  spyOnCamera,
  startMonitoring,
  unhandledRejections,
  waitForMoreFrames,
} from '../../support/monitor-page';

const AWAY_MS = 30000;

test.describe('captured frames', () => {
  test('sends each frame as a rising little endian capture time followed by a 640 x 480 JPEG', async ({ page }) => {
    const backend = await MockBackend.attach(page);

    await startMonitoring(page, backend);
    await waitForMoreFrames(backend, 6);
    const nowInPage = await page.evaluate(() => performance.now());

    const [streaming] = backend.openConnections();
    const frames = backend.framesOn(streaming.id);
    expect(frames.length).toBeGreaterThanOrEqual(6);
    expect(backend.textMessages).toEqual([]);
    for (const [index, frame] of frames.entries()) {
      expect(Number.isFinite(frame.captureMs)).toBe(true);
      expect(frame.captureMs).toBeGreaterThan(0);
      expect(frame.captureMs).toBeLessThanOrEqual(nowInPage);
      if (index > 0) {
        expect(frame.captureMs).toBeGreaterThan(frames[index - 1].captureMs);
      }
      expect([frame.jpeg[0], frame.jpeg[1]]).toEqual([0xff, 0xd8]);
      expect(jpegSize(frame.jpeg)).toEqual({ width: 640, height: 480 });
    }
  });

  test('keeps capture times rising with real clock readings after the tab was hidden', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    await startMonitoring(page, backend);
    await waitForMoreFrames(backend, 3);

    await setTabHidden(page, true);
    const hiddenAt = await pageNow(page);
    await page.clock.fastForward(AWAY_MS);
    await setTabHidden(page, false);
    const shownAt = await pageNow(page);
    await expect.poll(() => backend.frames.filter((frame) => frame.captureMs >= shownAt).length).toBeGreaterThanOrEqual(5);

    const now = await pageNow(page);
    const captureTimes = backend.frames.map((frame) => frame.captureMs);
    for (const [index, captureMs] of captureTimes.entries()) {
      if (index > 0) {
        expect(captureMs).toBeGreaterThan(captureTimes[index - 1]);
      }
      expect(captureMs).toBeLessThanOrEqual(now);
    }
    expect(shownAt - hiddenAt).toBeGreaterThanOrEqual(AWAY_MS);
  });

  for (const failure of ['yields no image', 'throws'] as const) {
    test(`shows FRAME_CAPTURE_FAILED, brings Start back and closes the socket when frame encoding ${failure}`, async ({
      page,
    }) => {
      await spyOnCamera(page);
      await recordUnhandledRejections(page);
      const backend = await MockBackend.attach(page);
      const monitor = monitorPage(page);
      await startMonitoring(page, backend);
      const [streaming] = backend.openConnections();

      await failFrameEncoding(page, failure);

      const alert = monitor.alertWith('FRAME_CAPTURE_FAILED');
      await expect(alert).toBeVisible();
      await expect(alert).toContainText(/frame/i);
      await expect(alert).toContainText(/\bStart\b/);
      await expect(alert).toContainText(/reload/i);
      expect(ownTextLength(await alert.innerText(), 'FRAME_CAPTURE_FAILED')).toBeGreaterThan(40);
      await expect(monitor.start).toBeVisible();
      await expect.poll(() => streaming.closedBy).toBe('page');
      expect(backend.openConnections()).toHaveLength(0);
      await expect.poll(async () => (await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
      expect(await unhandledRejections(page)).toEqual([]);
    });
  }
});
