import { expect, type Page } from '@playwright/test';
import { STREAM_URL, type FrameSend } from './socket-recorder';

export type FrameCallbacks = 'browser' | 'none' | 'capture time' | 'display time' | 'callback time';

export type FakeCamera = { frameMs: number; captureBeforeMs: number };

export const CAMERA_30_FPS: FakeCamera = { frameMs: 33, captureBeforeMs: 11.25 };

const CALLBACK_CLOCK_LEAD_MS = 5000;
const DISPLAY_AFTER_FRAME_MS = 16.375;
const PRESENTED_BEFORE_FRAME_MS = 0.625;
const DISPATCH_JITTER_MS = [0, 1.5, 3, 0.75, 2.25];
const TICK_MS = 2;
const SETTLE_POLL = { intervals: [1, 2, 5] };

export type DeliveredCallback = {
  order: number;
  presented: number;
  pageAt: number;
  now: number;
  captureTime: number | null;
  expectedDisplayTime: number | null;
};

export type VideoDraw = { order: number; at: number; inCallback: number | null };

export type NextFrame = { lateMs: number } | { captureShiftMs: number } | { dropped: true };

type Encodes = { inBrowser: number; reading: number; delaysMs: number[]; started: number };

type TimingLog = {
  order: number;
  delivered: DeliveredCallback[];
  sends: FrameSend[];
  draws: VideoDraw[];
  encodes: Encodes;
  inCallback: number | null;
  next: NextFrame | null;
  camera: FrameCallbacks | null;
};

type TimingWindow = Window & { frameTiming: TimingLog };

type FrameSink = { frames: Array<{ captureMs: number }> };

type Counts = { inBrowser: number; reading: number; sent: number; lastReplyT: number | null };

export type FrameTiming = { sends: FrameSend[]; draws: VideoDraw[]; delivered: DeliveredCallback[] };

export async function recordFrameTiming(
  page: Page,
  callbacks: FrameCallbacks,
  camera: FakeCamera = CAMERA_30_FPS,
): Promise<void> {
  await page.addInitScript(
    ({ mode, frameMs, lead, captureBefore, displayAfter, presentedBefore, jitters }) => {
      const owner = globalThis as unknown as Partial<TimingWindow>;
      if (owner.frameTiming === undefined) {
        const fresh: TimingLog = {
          order: 0,
          delivered: [],
          sends: [],
          draws: [],
          encodes: { inBrowser: 0, reading: 0, delaysMs: [], started: 0 },
          inCallback: null,
          next: null,
          camera: null,
        };
        Object.defineProperty(globalThis, 'frameTiming', { value: fresh });
        const drawImage = CanvasRenderingContext2D.prototype.drawImage;
        CanvasRenderingContext2D.prototype.drawImage = function recordedDraw(
          this: CanvasRenderingContext2D,
          ...args: unknown[]
        ) {
          if (args[0] instanceof HTMLVideoElement) {
            fresh.order += 1;
            fresh.draws.push({ order: fresh.order, at: performance.now(), inCallback: fresh.inCallback });
          }
          return Reflect.apply(drawImage, this, args) as void;
        };
        const toBlob = HTMLCanvasElement.prototype.toBlob;
        HTMLCanvasElement.prototype.toBlob = function trackedToBlob(
          this: HTMLCanvasElement,
          callback: BlobCallback,
          type?: string,
          quality?: number,
        ) {
          const { encodes } = fresh;
          const delay = encodes.delaysMs.length === 0 ? null : encodes.delaysMs[encodes.started % encodes.delaysMs.length];
          encodes.started += 1;
          encodes.inBrowser += 1;
          toBlob.call(
            this,
            (blob) => {
              encodes.inBrowser -= 1;
              if (blob !== null) {
                const read = blob.arrayBuffer.bind(blob);
                blob.arrayBuffer = () => {
                  encodes.reading += 1;
                  return read().finally(() => {
                    encodes.reading -= 1;
                  });
                };
              }
              if (delay === null) {
                callback(blob);
                return;
              }
              setTimeout(() => callback(blob), delay);
            },
            type,
            quality,
          );
        };
      }
      const log = (globalThis as unknown as TimingWindow).frameTiming;
      if (log.camera !== null) {
        return;
      }
      log.camera = mode;

      if (mode === 'browser') {
        return;
      }
      if (mode === 'none') {
        Reflect.deleteProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback');
        Reflect.deleteProperty(HTMLVideoElement.prototype, 'cancelVideoFrameCallback');
        return;
      }

      type Waiting = { video: HTMLVideoElement; callback: VideoFrameRequestCallback };
      const waiting = new Map<number, Waiting>();
      let lastHandle = 0;
      let presented = 0;
      let lastCaptureTime: number | null = null;
      let ticking = false;
      const dispatch = (due: Array<[number, Waiting]>, frameAt: number, metadata: Record<string, number>) => {
        const pageAt = performance.now();
        const now = frameAt - jitters[metadata.presentedFrames % jitters.length];
        log.order += 1;
        const order = log.order;
        log.delivered.push({
          order,
          presented: metadata.presentedFrames,
          pageAt,
          now,
          captureTime: metadata.captureTime ?? null,
          expectedDisplayTime: metadata.expectedDisplayTime ?? null,
        });
        for (const [, entry] of due) {
          log.inCallback = order;
          try {
            entry.callback(now, metadata as unknown as VideoFrameCallbackMetadata);
          } finally {
            log.inCallback = null;
          }
        }
      };
      const present = () => {
        presented += 1;
        const next = log.next;
        log.next = null;
        if (next !== null && 'dropped' in next) {
          return;
        }
        const due = [...waiting.entries()].filter(
          ([, entry]) => entry.video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && !entry.video.paused,
        );
        if (due.length === 0) {
          return;
        }
        for (const [handle] of due) {
          waiting.delete(handle);
        }
        const frameAt = performance.now() + lead;
        const metadata: Record<string, number> = {
          presentationTime: frameAt - presentedBefore,
          width: 640,
          height: 480,
          mediaTime: (presented * frameMs) / 1000,
          presentedFrames: presented,
          processingDuration: 0,
        };
        if (mode === 'capture time') {
          const shift = next !== null && 'captureShiftMs' in next ? next.captureShiftMs : null;
          metadata.captureTime =
            shift !== null && lastCaptureTime !== null ? lastCaptureTime + shift : frameAt - captureBefore;
          metadata.receiveTime = frameAt - presentedBefore;
          lastCaptureTime = metadata.captureTime;
        }
        if (mode !== 'callback time') {
          metadata.expectedDisplayTime = frameAt + displayAfter;
        }
        if (next !== null && 'lateMs' in next) {
          setTimeout(() => dispatch(due, frameAt, metadata), next.lateMs);
          return;
        }
        dispatch(due, frameAt, metadata);
      };
      HTMLVideoElement.prototype.requestVideoFrameCallback = function fakeFrameCallback(
        this: HTMLVideoElement,
        callback: VideoFrameRequestCallback,
      ) {
        if (!ticking) {
          ticking = true;
          setInterval(present, frameMs);
        }
        lastHandle += 1;
        waiting.set(lastHandle, { video: this, callback });
        return lastHandle;
      };
      HTMLVideoElement.prototype.cancelVideoFrameCallback = function cancelFakeFrameCallback(handle: number) {
        waiting.delete(handle);
      };
    },
    {
      mode: callbacks,
      frameMs: camera.frameMs,
      lead: CALLBACK_CLOCK_LEAD_MS,
      captureBefore: camera.captureBeforeMs,
      displayAfter: DISPLAY_AFTER_FRAME_MS,
      presentedBefore: PRESENTED_BEFORE_FRAME_MS,
      jitters: DISPATCH_JITTER_MS,
    },
  );
}

export function shapeNextCameraFrame(page: Page, next: NextFrame): Promise<void> {
  return page.evaluate((shape) => {
    (globalThis as unknown as TimingWindow).frameTiming.next = shape;
  }, next);
}

export function slowFrameEncoding(page: Page, delaysMs: number[]): Promise<void> {
  return page.evaluate((delays) => {
    const { encodes } = (globalThis as unknown as TimingWindow).frameTiming;
    encodes.delaysMs = delays;
    encodes.started = 0;
  }, delaysMs);
}

function timingLog(page: Page): Promise<TimingLog> {
  return page.evaluate(() => structuredClone((globalThis as unknown as TimingWindow).frameTiming));
}

export async function frameSends(page: Page): Promise<FrameSend[]> {
  return (await timingLog(page)).sends;
}

export async function timingSince(page: Page, order: number): Promise<FrameTiming> {
  const log = await timingLog(page);
  return {
    sends: log.sends.filter((send) => send.order > order),
    draws: log.draws,
    delivered: log.delivered,
  };
}

export function timingOrder(page: Page): Promise<number> {
  return page.evaluate(() => (globalThis as unknown as TimingWindow).frameTiming.order);
}

function timingCounts(page: Page): Promise<Counts> {
  return page.evaluate((url) => {
    const { encodes, sends } = (globalThis as unknown as TimingWindow).frameTiming;
    const records = (globalThis as unknown as { socketRecords: Array<{ url: string; messages: Array<{ text: string }> }> })
      .socketRecords;
    const last = records.findLast((record) => record.url === url)?.messages.at(-1);
    let lastReplyT: number | null = null;
    if (last !== undefined) {
      const fields: unknown = JSON.parse(last.text);
      if (typeof fields === 'object' && fields !== null && 'type' in fields && fields.type === 'frame' && 't' in fields) {
        lastReplyT = Number(fields.t);
      }
    }
    return { inBrowser: encodes.inBrowser, reading: encodes.reading, sent: sends.length, lastReplyT };
  }, STREAM_URL);
}

async function unsettled(page: Page, backend: FrameSink): Promise<string> {
  const { inBrowser, reading, sent, lastReplyT } = await timingCounts(page);
  if (inBrowser > 0) {
    return `${inBrowser} encodes still in the browser`;
  }
  if (reading > 0) {
    return `${reading} encoded frames still being read`;
  }
  if (backend.frames.length < sent) {
    return `${sent - backend.frames.length} sent frames not at the backend yet`;
  }
  const latest = backend.frames.at(-1);
  if (latest !== undefined && lastReplyT !== Math.floor(latest.captureMs)) {
    return `latest frame ${Math.floor(latest.captureMs)} awaits its reply, last reply ${String(lastReplyT)}`;
  }
  return 'settled';
}

export async function settleFrames(page: Page, backend: FrameSink): Promise<void> {
  await expect.poll(() => unsettled(page, backend), SETTLE_POLL).toBe('settled');
}

export async function stepClock(page: Page, backend: FrameSink, ms: number): Promise<void> {
  for (let spent = 0; spent < ms; spent += TICK_MS) {
    await page.clock.runFor(TICK_MS);
    await settleFrames(page, backend);
  }
}

export async function stepClockUntil(page: Page, backend: FrameSink, done: () => boolean, budgetMs: number): Promise<void> {
  for (let spent = 0; !done(); spent += TICK_MS) {
    expect(spent, 'page time stepped waiting for frames').toBeLessThan(budgetMs);
    await stepClock(page, backend, TICK_MS);
  }
}

export function gapsBetween(times: number[]): number[] {
  return times.slice(1).map((time, index) => time - times[index]);
}
