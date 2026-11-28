import { expect, test, type Page } from '@playwright/test';
import { FRAME_SPACING_MS, guidedPage, openGuidedRun, pauseClock } from '../../support/guided-page';
import {
  CAMERA_30_FPS,
  gapsBetween,
  recordFrameTiming,
  shapeNextCameraFrame,
  stepClock,
  stepClockUntil,
  timingOrder,
  timingSince,
  type DeliveredCallback,
  type FakeCamera,
  type FrameCallbacks,
  type FrameTiming,
  type VideoDraw,
} from '../../support/frame-timing';
import { faceScene, MockBackend } from '../../support/mock-backend';
import type { FrameSend } from '../../support/socket-recorder';

const RUN_FOR_MS = 20 * FRAME_SPACING_MS;
const MIN_FRAMES = 10;
const SAME_MS = 0.001;
const START_BUDGET_MS = 2000;
const SLOW_CAMERA: FakeCamera = { frameMs: 36, captureBeforeMs: 60 };
const LATE_CALLBACK_MS = [12, 40];
const REUSED_CAPTURE = [
  { shiftMs: 0, how: 'the same as the frame before' },
  { shiftMs: -5, how: 'older than the frame before' },
];

type Field = (callback: DeliveredCallback) => number | null;

type Stamped = { send: FrameSend; draw: VideoDraw | undefined; callback: DeliveredCallback | undefined };

async function openStampedCheck(
  page: Page,
  callbacks: FrameCallbacks,
  camera: FakeCamera = CAMERA_30_FPS,
): Promise<{ backend: MockBackend; from: number }> {
  await recordFrameTiming(page, callbacks, camera);
  const backend = await MockBackend.attach(page);
  backend.setScene(faceScene({ moving: true }));
  await page.clock.install();
  await openGuidedRun(page);
  await pauseClock(page);
  await guidedPage(page).start.click();
  await stepClockUntil(page, backend, () => backend.frames.length > 1, START_BUDGET_MS);
  return { backend, from: await timingOrder(page) };
}

function stamped({ sends, draws, delivered }: FrameTiming): Stamped[] {
  return sends.map((send) => {
    const draw = draws.findLast((each) => each.order < send.order);
    const callback = delivered.find((each) => draw !== undefined && each.order === draw.inCallback);
    return { send, draw, callback };
  });
}

function baseOffset({ delivered }: FrameTiming, callback: DeliveredCallback): number {
  const upTo = delivered.filter((each) => each.order <= callback.order);
  return Math.min(...upTo.map((each) => each.pageAt - each.now));
}

function expectCallbackStamps(timing: FrameTiming, field: Field): Stamped[] {
  const frames = stamped(timing);
  expect(frames.length, 'frames sent while the clock ran').toBeGreaterThanOrEqual(MIN_FRAMES);
  for (const [index, { send, draw, callback }] of frames.entries()) {
    expect(draw, `frame ${index} drew the video before it was sent`).toBeDefined();
    expect(draw?.inCallback ?? null, `frame ${index} was drawn inside a video frame callback`).not.toBeNull();
    const value = callback === undefined ? null : field(callback);
    expect(value, `the callback field behind frame ${index}`).not.toBeNull();
    expect(
      Math.abs(send.captureMs - ((value ?? Number.NaN) + (callback === undefined ? Number.NaN : baseOffset(timing, callback)))),
      `frame ${index} stamp against its callback field plus the lowest offset so far`,
    ).toBeLessThan(SAME_MS);
  }
  const pictures = frames.map((frame) => frame.callback?.order);
  expect(new Set(pictures).size, 'distinct camera frames among the frames sent').toBe(pictures.length);
  const wholeMs = frames.map((frame) => Math.floor(frame.send.captureMs));
  expect(gapsBetween(wholeMs).filter((gap) => gap <= 0), 'whole ms stamps that did not rise').toEqual([]);
  return frames;
}

const FIELDS: Array<{ callbacks: FrameCallbacks; title: string; field: Field }> = [
  {
    callbacks: 'capture time',
    title: "the video frame's captureTime when the frame callback gives one",
    field: (callback) => callback.captureTime,
  },
  {
    callbacks: 'display time',
    title: 'the expectedDisplayTime when the frame callback gives no captureTime',
    field: (callback) => callback.expectedDisplayTime,
  },
  {
    callbacks: 'callback time',
    title: "the callback's own time when the frame callback gives neither captureTime nor expectedDisplayTime",
    field: (callback) => callback.now,
  },
];

const captureTime: Field = (callback) => callback.captureTime;

test.describe('frame capture time', () => {
  for (const { callbacks, title, field } of FIELDS) {
    test(`stamps each frame drawn in its frame callback with ${title}, moved by the lowest clock offset seen so far`, async ({
      page,
    }) => {
      const { backend, from } = await openStampedCheck(page, callbacks);
      await stepClock(page, backend, RUN_FOR_MS);

      expectCallbackStamps(await timingSince(page, from), field);
      expect(backend.textMessages).toEqual([]);
      await expect(guidedPage(page).alert).toHaveCount(0);
    });
  }

  test('never sends a send time stamp or the same picture twice when the camera runs slower than the pump and its capture time leads its callback by 60 ms', async ({
    page,
  }) => {
    const { backend, from } = await openStampedCheck(page, 'capture time', SLOW_CAMERA);
    await stepClock(page, backend, RUN_FOR_MS);

    const timing = await timingSince(page, from);
    const frames = expectCallbackStamps(timing, captureTime);
    const sendTimes = new Set(timing.sends.map((send) => send.at));
    expect(frames.filter(({ send }) => sendTimes.has(send.captureMs)), 'frames stamped with a send time').toEqual([]);
    expect(Math.min(...gapsBetween(timing.sends.map((send) => send.at))), 'closest two sends, in ms').toBeGreaterThanOrEqual(
      FRAME_SPACING_MS,
    );
  });

  for (const lateMs of LATE_CALLBACK_MS) {
    test(`keeps the lowest clock offset, so a frame callback ${lateMs} ms late and the next one still stamp their capture times`, async ({
      page,
    }) => {
      const { backend, from } = await openStampedCheck(page, 'capture time');
      await stepClock(page, backend, RUN_FOR_MS / 2);
      await shapeNextCameraFrame(page, { lateMs });
      await stepClock(page, backend, RUN_FOR_MS / 2);

      const timing = await timingSince(page, from);
      const frames = expectCallbackStamps(timing, captureTime);
      const lowest = Math.min(...timing.delivered.map((each) => each.pageAt - each.now));
      const late = timing.delivered.filter((each) => each.pageAt - each.now - lowest >= lateMs);
      expect(late.length, `callbacks that ran ${lateMs} ms late`).toBe(1);
      const next = timing.delivered.find((each) => each.order > late[0].order);
      const sentPictures = frames.map((frame) => frame.callback?.order);
      expect(sentPictures, 'the late callback was sent').toContain(late[0].order);
      expect(sentPictures, 'the callback after the late one was sent').toContain(next?.order);
    });
  }

  for (const { shiftMs, how } of REUSED_CAPTURE) {
    test(`sends nothing for a frame callback whose captureTime is ${how}, and sends the next fresh one`, async ({ page }) => {
      const { backend, from } = await openStampedCheck(page, 'capture time');
      await stepClock(page, backend, RUN_FOR_MS / 2);
      await shapeNextCameraFrame(page, { captureShiftMs: shiftMs });
      await stepClock(page, backend, RUN_FOR_MS / 2);

      const timing = await timingSince(page, from);
      const frames = expectCallbackStamps(timing, captureTime);
      const reused = timing.delivered.filter(
        (each, index) =>
          index > 0 && each.captureTime !== null && each.captureTime <= (timing.delivered[index - 1].captureTime ?? 0),
      );
      expect(reused.length, `callbacks whose captureTime is ${how}`).toBe(1);
      const next = timing.delivered.find((each) => each.order > reused[0].order);
      const sentPictures = frames.map((frame) => frame.callback?.order);
      expect(sentPictures, 'the reused capture time was not sent').not.toContain(reused[0].order);
      expect(sentPictures, 'the next fresh callback was sent').toContain(next?.order);
    });
  }

  test('keeps stamping capture times when the camera skips a frame callback, a guard', async ({ page }) => {
    const { backend, from } = await openStampedCheck(page, 'capture time');
    await stepClock(page, backend, RUN_FOR_MS / 2);
    await shapeNextCameraFrame(page, { dropped: true });
    await stepClock(page, backend, RUN_FOR_MS / 2);

    const timing = await timingSince(page, from);
    const delivered = timing.delivered.filter((callback) => callback.order > from);
    const skips = gapsBetween(delivered.map((callback) => callback.presented)).filter((gap) => gap > 1);
    expect(skips, 'camera frames that brought no callback').toEqual([2]);
    expectCallbackStamps(timing, captureTime);
  });

  test('stamps each frame header with the time its send started when the browser has no video frame callback', async ({
    page,
  }) => {
    const { backend, from } = await openStampedCheck(page, 'none');
    await stepClock(page, backend, RUN_FOR_MS);

    const frames = stamped(await timingSince(page, from));
    expect(frames.length, 'frames sent while the clock ran').toBeGreaterThanOrEqual(MIN_FRAMES);
    for (const [index, { send, draw }] of frames.entries()) {
      expect(draw, `frame ${index} drew the video before it was sent`).toBeDefined();
      expect(send.captureMs, `frame ${index} stamp against its draw time`).toBe(draw?.at);
    }
    const wholeMs = frames.map((frame) => Math.floor(frame.send.captureMs));
    expect(gapsBetween(wholeMs).filter((gap) => gap <= 0), 'whole ms stamps that did not rise').toEqual([]);
    expect(backend.textMessages).toEqual([]);
    await expect(guidedPage(page).alert).toHaveCount(0);
  });
});
