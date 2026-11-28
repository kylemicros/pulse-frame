import { expect, test, type Page } from '@playwright/test';
import { FRAME_SPACING_MS, guidedPage, paceReplies, pauseClock, SLOW_STEP_MS, startCheck } from '../../support/guided-page';
import {
  frameSends,
  gapsBetween,
  recordFrameTiming,
  settleFrames,
  slowFrameEncoding,
  stepClock,
  type FrameCallbacks,
} from '../../support/frame-timing';
import { faceScene, MockBackend } from '../../support/mock-backend';
import { pageNow } from '../../support/page-helpers';

const SLOW_ENCODE_MS = 25;
const LONG_ENCODE_MS = 30;
const SHORT_ENCODE_MS = 4;
const SWINGING_ENCODE_MS = [LONG_ENCODE_MS, SHORT_ENCODE_MS];
const SWING_PAIR_MS = 2 * FRAME_SPACING_MS + LONG_ENCODE_MS - SHORT_ENCODE_MS;
const OLD_SWING_SENDS = 27;
const WARM_MS = 6 * FRAME_SPACING_MS;
const MEASURE_MS = 40 * FRAME_SPACING_MS;
const FLOOR_SENDS = MEASURE_MS / FRAME_SPACING_MS;
const NEAR_FLOOR_SENDS = Math.floor(FLOOR_SENDS * 0.9);
const SPEED_SETTLE_MS = 1500;
const SWING_START_PACED_SENDS = Math.floor((2 * MEASURE_MS) / SWING_PAIR_MS);
const HOLD_ENCODES_MS = [...Array.from({ length: 6 }, () => LONG_ENCODE_MS), SHORT_ENCODE_MS];
const MIN_HOLD_SENDS = 2 * HOLD_ENCODES_MS.length;

async function openPacedCheck(page: Page, callbacks: FrameCallbacks): Promise<MockBackend> {
  await recordFrameTiming(page, callbacks);
  const backend = await MockBackend.attach(page);
  backend.setScene(faceScene({ moving: true }));
  await page.clock.install();
  await startCheck(page, backend);
  await pauseClock(page);
  await settleFrames(page, backend);
  return backend;
}

async function sendsWhileMeasuring(page: Page, backend: MockBackend): Promise<number[]> {
  await stepClock(page, backend, WARM_MS);
  const from = await pageNow(page);
  await stepClock(page, backend, MEASURE_MS);
  const to = await pageNow(page);
  return (await frameSends(page)).map((send) => send.at).filter((at) => at >= from && at < to);
}

test.describe('frame pacing', () => {
  for (const [callbacks, how] of [
    ['capture time', 'with the video frame callback'],
    ['none', 'without the video frame callback'],
  ] as const) {
    test(`keeps sending near the 34 ms floor's rate when each encode takes 25 ms, ${how}`, async ({ page }) => {
      const backend = await openPacedCheck(page, callbacks);
      await slowFrameEncoding(page, [SLOW_ENCODE_MS]);

      const sent = await sendsWhileMeasuring(page, backend);

      expect(sent.length, `frames sent in ${MEASURE_MS} ms of page time`).toBeGreaterThanOrEqual(NEAR_FLOOR_SENDS);
      expect(sent.length, `frames sent in ${MEASURE_MS} ms of page time`).toBeLessThanOrEqual(FLOOR_SENDS + 1);
      expect(Math.min(...gapsBetween(sent)), 'closest two sends, in ms').toBeGreaterThanOrEqual(FRAME_SPACING_MS);
      expect(backend.frames.filter((frame) => frame.arrivedWhileAwaitingReply)).toEqual([]);
    });
  }

  test('keeps sends 34 ms apart with one frame in flight, faster than send after encode pacing, while the encode swings between 30 ms and 4 ms', async ({
    page,
  }) => {
    const backend = await openPacedCheck(page, 'capture time');
    await slowFrameEncoding(page, SWINGING_ENCODE_MS);

    const sent = await sendsWhileMeasuring(page, backend);

    expect(Math.min(...gapsBetween(sent)), 'closest two sends, in ms').toBeGreaterThanOrEqual(FRAME_SPACING_MS);
    expect(
      sent.length,
      `frames sent in ${MEASURE_MS} ms against start paced sending, two per ${SWING_PAIR_MS} ms`,
    ).toBeGreaterThanOrEqual(SWING_START_PACED_SENDS);
    expect(sent.length, 'frames sent against the old send after encode pacing').toBeGreaterThan(OLD_SWING_SENDS);
    expect(backend.frames.filter((frame) => frame.arrivedWhileAwaitingReply)).toEqual([]);
  });

  test('holds frames from a 33 ms camera to the 34 ms floor when encodes run 30 ms with an odd 4 ms one', async ({
    page,
  }) => {
    const backend = await openPacedCheck(page, 'capture time');
    await slowFrameEncoding(page, HOLD_ENCODES_MS);

    const sent = await sendsWhileMeasuring(page, backend);

    expect(sent.length, `frames sent in ${MEASURE_MS} ms of page time`).toBeGreaterThanOrEqual(MIN_HOLD_SENDS);
    expect(Math.min(...gapsBetween(sent)), 'closest two sends, in ms').toBeGreaterThanOrEqual(FRAME_SPACING_MS);
    expect(backend.frames.filter((frame) => frame.arrivedWhileAwaitingReply)).toEqual([]);
  });

  test('keeps sending near the 34 ms floor rate without the video frame callback while the encode swings between 30 ms and 4 ms', async ({
    page,
  }) => {
    const backend = await openPacedCheck(page, 'none');
    await slowFrameEncoding(page, SWINGING_ENCODE_MS);

    const sent = await sendsWhileMeasuring(page, backend);

    expect(Math.min(...gapsBetween(sent)), 'closest two sends, in ms').toBeGreaterThanOrEqual(FRAME_SPACING_MS);
    expect(
      sent.length,
      `frames sent in ${MEASURE_MS} ms, against ${SWING_START_PACED_SENDS} when the encode history delays each start`,
    ).toBeGreaterThanOrEqual(NEAR_FLOOR_SENDS);
    expect(backend.frames.filter((frame) => frame.arrivedWhileAwaitingReply)).toEqual([]);
  });

  test('shows Camera speed Good when each encode takes 25 ms but every reply comes straight back', async ({ page }) => {
    const backend = await openPacedCheck(page, 'capture time');
    await slowFrameEncoding(page, [SLOW_ENCODE_MS]);

    await stepClock(page, backend, SPEED_SETTLE_MS);

    const speed = guidedPage(page).setupRow('Camera speed');
    await expect(speed.getByText('Good', { exact: true })).toBeVisible();
    await expect(speed.getByText('Not yet', { exact: true })).toHaveCount(0);
  });

  test('counts replies for Camera speed, so it stays Not yet when replies lag while the camera runs at 30 frames a second', async ({
    page,
  }) => {
    const backend = await openPacedCheck(page, 'capture time');

    await paceReplies(page, backend, SPEED_SETTLE_MS, SLOW_STEP_MS);

    const speed = guidedPage(page).setupRow('Camera speed');
    await expect(speed.getByText('Not yet', { exact: true })).toBeVisible();
    await expect(speed.getByText('Good', { exact: true })).toHaveCount(0);
  });
});
