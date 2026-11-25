import { expect, test } from '@playwright/test';
import { expectQuietRef, guidedPage, startRun } from '../../support/guided-page';
import { JPEG_CAP_BYTES, jpegQuality, jpegSize } from '../../support/jpeg';
import { MockBackend } from '../../support/mock-backend';
import {
  cameraTrackStates,
  encodeEveryFrameOverCap,
  failFrameEncoding,
  pageNow,
  recordUnhandledRejections,
  setTabHidden,
  showCameraView,
  spyOnCamera,
  unhandledRejections,
  useDrawnCamera,
  waitForMoreFrames,
} from '../../support/page-helpers';

const AWAY_MS = 30000;
const VIEW_SETTLE_MS = 500;

test.describe('captured frames', () => {
  test('sends each frame as a rising little endian capture time followed by a 640 x 480 JPEG', async ({ page }) => {
    const backend = await MockBackend.attach(page);

    await startRun(page, backend);
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

  test('keeps capture times rising with real clock readings across a hidden tab and Start again', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await waitForMoreFrames(backend, 3);

    await setTabHidden(page, true);
    const hiddenAt = await pageNow(page);
    await page.clock.fastForward(AWAY_MS);
    await setTabHidden(page, false);
    await guided.startAgain.click();
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

  test('encodes every frame at JPEG quality 95 and keeps it under the 204,800 byte cap', async ({ page }) => {
    const backend = await MockBackend.attach(page);

    await startRun(page, backend);
    await waitForMoreFrames(backend, 6);

    expect(backend.frames.length).toBeGreaterThanOrEqual(6);
    for (const frame of backend.frames) {
      expect(jpegQuality(frame.jpeg), 'the quality the frame was encoded at').toBe(95);
      expect(frame.jpeg.length).toBeLessThanOrEqual(JPEG_CAP_BYTES);
    }
  });

  test('re-encodes a frame that would pass the 204,800 byte cap at a lower quality and never sends it over the cap', async ({
    page,
  }) => {
    await useDrawnCamera(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await waitForMoreFrames(backend, 4);
    const plainBefore = backend.frames.length;
    expect(backend.frames.map((frame) => jpegQuality(frame.jpeg))).toEqual(Array(plainBefore).fill(95));

    const busyFrom = (await pageNow(page)) + VIEW_SETTLE_MS;
    await showCameraView(page, 'busy');
    await expect.poll(() => backend.frames.filter((frame) => frame.captureMs >= busyFrom).length).toBeGreaterThanOrEqual(5);
    const plainFrom = (await pageNow(page)) + VIEW_SETTLE_MS;
    const busy = backend.frames.filter((frame) => frame.captureMs >= busyFrom);

    for (const frame of busy) {
      expect(jpegSize(frame.jpeg)).toEqual({ width: 640, height: 480 });
      expect(frame.jpeg.length).toBeLessThanOrEqual(JPEG_CAP_BYTES);
      expect(jpegQuality(frame.jpeg), 'the quality of a busy frame').toBeLessThan(95);
    }

    await showCameraView(page, 'plain');
    await expect.poll(() => backend.frames.filter((frame) => frame.captureMs >= plainFrom).length).toBeGreaterThanOrEqual(4);
    const plainAgain = backend.frames.filter((frame) => frame.captureMs >= plainFrom);
    expect(plainAgain.map((frame) => jpegQuality(frame.jpeg))).toEqual(Array(plainAgain.length).fill(95));

    expect(backend.frames.filter((frame) => frame.jpeg.length > JPEG_CAP_BYTES)).toEqual([]);
    expect(backend.textMessages).toEqual([]);
    await expect(guided.alert).toHaveCount(0);
    await expect(guided.main.getByText(/^Ref: /)).toHaveCount(0);
    await expect(guided.stop).toBeVisible();
  });

  test('shows FRAME_CAPTURE_FAILED, offers Start again and sends nothing over the cap when every quality stays over it', async ({
    page,
  }) => {
    await recordUnhandledRejections(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    const [streaming] = backend.openConnections();

    await encodeEveryFrameOverCap(page, JPEG_CAP_BYTES + 1);

    await expectQuietRef(guided.main, "Reading the camera's video failed, so the run stopped.", 'FRAME_CAPTURE_FAILED');
    await expect(guided.startAgain).toBeVisible();
    await expect.poll(() => streaming.closedBy).toBe('page');
    expect(backend.openConnections()).toHaveLength(0);
    expect(backend.frames.filter((frame) => frame.jpeg.length > JPEG_CAP_BYTES)).toEqual([]);
    expect(await unhandledRejections(page)).toEqual([]);
  });

  for (const failure of ['yields no image', 'throws'] as const) {
    test(`shows FRAME_CAPTURE_FAILED, offers Start again and closes the socket when frame encoding ${failure}`, async ({
      page,
    }) => {
      await spyOnCamera(page);
      await recordUnhandledRejections(page);
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      await startRun(page, backend);
      const [streaming] = backend.openConnections();

      await failFrameEncoding(page, failure);

      await expectQuietRef(guided.main, "Reading the camera's video failed, so the run stopped.", 'FRAME_CAPTURE_FAILED');
      await expect(guided.main.getByText('Press Start again. If it keeps happening, reload the page.')).toBeVisible();
      await expect(guided.startAgain).toBeVisible();
      await expect.poll(() => streaming.closedBy).toBe('page');
      expect(backend.openConnections()).toHaveLength(0);
      await expect.poll(async () => (await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
      expect(await unhandledRejections(page)).toEqual([]);
    });
  }
});
